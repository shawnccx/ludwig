import os

import pytest

from ludwig.constants import (
    COLUMN,
    DECODER,
    DEFAULTS,
    ENCODER,
    INPUT_FEATURES,
    NAME,
    OUTPUT_FEATURES,
    SEQUENCE,
    TEXT,
    TYPE,
)
from tests.integration_tests.utils import (
    create_data_set_to_use,
    generate_data,
    RAY_BACKEND_CONFIG,
    sequence_feature,
    text_feature,
    train_with_backend,
)


@pytest.mark.parametrize("feature_type,feature_gen", [(TEXT, text_feature), (SEQUENCE, sequence_feature)])
@pytest.mark.parametrize("decoder_type", ["generator", "tagger"])
@pytest.mark.parametrize("use_defaults", [True, False])
@pytest.mark.distributed
def test_sequence_decoder_predictions(
    tmpdir, csv_filename, ray_cluster_2cpu, feature_type, feature_gen, use_defaults, decoder_type
):
    """Test that sequence decoders return the correct successfully predict."""
    input_feature = feature_gen()
    output_feature = feature_gen(output_feature=True)

    input_feature[ENCODER] = {TYPE: "parallel_cnn", "reduce_output": None}
    output_feature[DECODER] = {TYPE: decoder_type}

    dataset_path = generate_data(
        input_features=[input_feature],
        output_features=[output_feature],
        filename=os.path.join(tmpdir, csv_filename),
    )
    dataset_path = create_data_set_to_use("csv", dataset_path)

    config = {INPUT_FEATURES: [input_feature]}

    # Ensure that the decoder outputs the correct predictions through both the default and feature-specific configs.
    if use_defaults:
        config[OUTPUT_FEATURES] = [{TYPE: feature_type, NAME: output_feature[NAME], COLUMN: output_feature[COLUMN]}]
        config[DEFAULTS] = {feature_type: {DECODER: {TYPE: decoder_type}}}
    else:
        config[OUTPUT_FEATURES] = [output_feature]

    # Test with decoder in output feature config
    train_with_backend(RAY_BACKEND_CONFIG, config=config, dataset=dataset_path)
