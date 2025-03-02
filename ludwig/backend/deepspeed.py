from typing import Any, Dict, Optional, Type

import deepspeed

from ludwig.backend.base import DataParallelBackend
from ludwig.constants import FALLBACK_BATCH_SIZE
from ludwig.distributed import init_dist_strategy
from ludwig.utils.batch_size_tuner import BatchSizeEvaluator


class DeepSpeedBackend(DataParallelBackend):
    BACKEND_TYPE = "deepspeed"

    def __init__(self, zero_optimization: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(**kwargs)
        self.zero_optimization = zero_optimization

    def initialize(self):
        # Unlike when we use the Ray backend, we need to initialize the `torch.distributed` context so we can
        # broadcast, allgather, etc. before preparing the model within the trainer.
        deepspeed.init_distributed()
        self._distributed = init_dist_strategy(self.BACKEND_TYPE, zero_optimization=self.zero_optimization)

    def supports_batch_size_tuning(self) -> bool:
        # TODO(travis): need to fix checkpoint saving/loading for DeepSpeed to enable tuning
        return False

    def tune_batch_size(self, evaluator_cls: Type[BatchSizeEvaluator], dataset_len: int) -> int:
        return FALLBACK_BATCH_SIZE
