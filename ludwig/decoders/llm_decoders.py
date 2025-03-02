import logging
import re
from typing import Any, Dict, Union

import torch

from ludwig.api_annotations import DeveloperAPI
from ludwig.constants import CATEGORY, LOGITS, PREDICTIONS, PROBABILITIES, TEXT
from ludwig.decoders.base import Decoder
from ludwig.decoders.registry import register_decoder
from ludwig.decoders.utils import extract_generated_tokens
from ludwig.schema.decoders.llm_decoders import CategoryParserDecoderConfig, TextParserDecoderConfig
from ludwig.utils.strings_utils import get_tokenizer

logger = logging.getLogger(__name__)


# TODO(Arnav): Refactor to split into strategies like splitters
class Matcher:
    def __init__(self, match: Dict[str, Dict[str, Any]]):
        self.match = match

    def contains(self, decoded_input: str, value: str) -> bool:
        return value in decoded_input

    def regex(self, decoded_input: str, regex_pattern: str) -> bool:
        """Perform a regex match on a given text using a specified regex pattern.

        Parameters:
        text (str): The text to perform the match on.
        regex_pattern (str): The regex pattern to use for the match.

        Returns:
        A list of match objects.
        """
        # Compile the regex pattern
        matches = []
        try:
            regex = re.compile(regex_pattern)
            # Perform the match
            matches = regex.findall(decoded_input)
        except Exception:
            logger.warning(f"Regex pattern {regex_pattern} could not be compiled.")
        # If there is a match, matches is a non-empty list, so we can use this
        # to infer if there was a match or not and return a bool
        return len(matches) > 0

    def __call__(self, decoded_input: str) -> Union[str, None]:
        # Greedy match on first label that matches the input
        for label, label_def in self.match.items():
            label_def_type = label_def["type"]
            label_def_value = label_def["value"]

            if label_def_type == "contains":
                is_match = self.contains(decoded_input, label_def_value)
            elif label_def_type == "regex":
                is_match = self.regex(decoded_input, label_def_value)
            else:
                raise ValueError(
                    f"{label_def_type} is not a valid match `type`. Ludwig "
                    "currently supports `contains` and `regex` match types."
                )

            if is_match:
                return label
        return None


@DeveloperAPI
@register_decoder("text_parser", [TEXT])
class TextParserDecoder(Decoder):
    def __init__(
        self,
        input_size: int,
        decoder_config=None,
        **kwargs,
    ):
        super().__init__()
        self.config = decoder_config
        self.input_size = input_size

        # Tokenizer
        self.tokenizer_type = self.config.tokenizer
        self.pretrained_model_name_or_path = self.config.pretrained_model_name_or_path
        self.vocab_file = self.config.vocab_file

        # Load tokenizer required for decoding the output from the generate
        # function of the text input feature for LLMs.
        self.tokenizer = get_tokenizer(self.tokenizer_type, self.vocab_file, self.pretrained_model_name_or_path)
        self.tokenizer_vocab_size = self.tokenizer.tokenizer.vocab_size

        # Maximum number of new tokens that will be generated
        self.max_new_tokens = self.config.max_new_tokens

    @staticmethod
    def get_schema_cls():
        return TextParserDecoderConfig

    @property
    def input_shape(self):
        return self.input_size

    def get_prediction_set(self):
        return {LOGITS, PREDICTIONS, PROBABILITIES}

    def forward(self, inputs, **kwargs):
        # Extract the sequences tensor from the LLMs forward pass
        generated_outputs = extract_generated_tokens(
            raw_generated_output_sequences=inputs.sequences,
            llm_model_inputs=kwargs.get("llm_model_inputs", []),
            max_new_tokens=self.max_new_tokens,
            pad_sequence=True,
        )

        return {
            PREDICTIONS: generated_outputs,
            # TODO(Arnav): Add support for probabilities and logits
            PROBABILITIES: torch.zeros((len(generated_outputs), self.max_new_tokens, self.tokenizer_vocab_size)),
            LOGITS: torch.zeros((len(generated_outputs), self.max_new_tokens, self.tokenizer_vocab_size)),
        }


@DeveloperAPI
@register_decoder("category_parser", [CATEGORY])
class CategoryParserDecoder(Decoder):
    def __init__(
        self,
        decoder_config=None,
        **kwargs,
    ):
        super().__init__()
        self.config = decoder_config

        self.input_size = self.config.input_size
        self.fallback_label = self.config.fallback_label
        self.str2idx = self.config.str2idx
        self.vocab_size = len(self.config.str2idx)

        # Create Matcher object to perform matching on the decoded output
        self.matcher = Matcher(self.config.match)

        # Tokenizer
        self.tokenizer_type = self.config.tokenizer
        self.pretrained_model_name_or_path = self.config.pretrained_model_name_or_path
        self.vocab_file = self.config.vocab_file

        # Load tokenizer required for decoding the output from the generate
        # function of the text input feature for LLMs.
        self.tokenizer = get_tokenizer(self.tokenizer_type, self.vocab_file, self.pretrained_model_name_or_path)

    @staticmethod
    def get_schema_cls():
        return CategoryParserDecoderConfig

    @property
    def input_shape(self):
        return self.input_size

    def get_prediction_set(self):
        return {LOGITS, PREDICTIONS, PROBABILITIES}

    def forward(self, inputs, **kwargs):
        # Extract the sequences tensor from the LLMs forward pass
        generated_outputs = extract_generated_tokens(
            raw_generated_output_sequences=inputs.sequences,
            llm_model_inputs=kwargs.get("llm_model_inputs", []),
            max_new_tokens=None,
            pad_sequence=False,
        )

        # Decode generated outputs from the LLM's generate function.
        decoded_outputs = self.tokenizer.tokenizer.batch_decode(generated_outputs, skip_special_tokens=True)
        logger.info(f"Decoded output: {decoded_outputs}")

        # Parse labels based on matching criteria and return probability vectors
        matched_labels = []
        probabilities = []
        logits = []
        for output in decoded_outputs:
            matched_label = self.matcher(output)
            idx = self.str2idx[matched_label] if matched_label in self.str2idx else self.str2idx[self.fallback_label]

            # Append the index of the matched label
            matched_labels.append(idx)

            # Append the probability vector for the matched label
            probability_vec = [0] * self.vocab_size
            probability_vec[idx] = 1
            probabilities.append(probability_vec)

            # TODO(Arnav): Figure out how to compute logits. For now, we return
            # a tensor of zeros.
            logits.append([0] * self.vocab_size)

        return {
            PREDICTIONS: torch.tensor(matched_labels),
            PROBABILITIES: torch.tensor(probabilities, dtype=torch.float32),
            LOGITS: torch.tensor(logits, dtype=torch.float32),
        }
