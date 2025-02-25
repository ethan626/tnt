#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import unittest
from unittest.mock import patch

import torch
from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
from torch.distributed.fsdp.fully_sharded_data_parallel import MixedPrecision
from torch.nn.parallel import DistributedDataParallel as DDP
from torchtnt.utils.env import init_from_env
from torchtnt.utils.prepare_module import (
    _is_fsdp_module,
    DDPStrategy,
    FSDPStrategy,
    prepare_ddp,
    prepare_fsdp,
    prepare_module,
    SWAParams,
    TorchCompileParams,
)
from torchtnt.utils.test_utils import spawn_multi_process
from torchtnt.utils.version import is_torch_version_geq_1_13, is_torch_version_geq_2_0

COMPILE_AVAIL = False
if is_torch_version_geq_1_13():
    COMPILE_AVAIL = True
    import torch._dynamo

if is_torch_version_geq_2_0():
    from torch.distributed._composable import fully_shard


class PrepareModelTest(unittest.TestCase):

    cuda_available: bool = torch.cuda.is_available()
    distributed_available: bool = torch.distributed.is_available()

    @unittest.skipUnless(
        condition=(cuda_available), reason="This test should run on a GPU host."
    )
    @unittest.skipUnless(
        distributed_available, reason="Torch distributed is needed to run"
    )
    def test_prepare_ddp(self) -> None:
        spawn_multi_process(
            2,
            "nccl",
            self._test_prepare_ddp,
        )

    @staticmethod
    def _test_prepare_ddp() -> None:
        module = torch.nn.Linear(2, 2)
        device = init_from_env()
        ddp_module = prepare_ddp(
            module,
            device,
            DDPStrategy(find_unused_parameters=True, gradient_as_bucket_view=True),
        )
        tc = unittest.TestCase()
        tc.assertTrue(isinstance(ddp_module, DDP))

    @unittest.skipUnless(
        condition=(cuda_available), reason="This test should run on a GPU host."
    )
    @unittest.skipUnless(
        distributed_available, reason="Torch distributed is needed to run"
    )
    def test_prepare_fsdp(self) -> None:
        spawn_multi_process(
            2,
            "nccl",
            self._test_prepare_fsdp,
        )

    @staticmethod
    def _test_prepare_fsdp() -> None:
        module = torch.nn.Linear(2, 2)
        device = init_from_env()
        fsdp_module = prepare_fsdp(module, device, FSDPStrategy(limit_all_gathers=True))
        tc = unittest.TestCase()
        tc.assertTrue(isinstance(fsdp_module, FSDP))

    @unittest.skipUnless(
        distributed_available, reason="Torch distributed is needed to run"
    )
    @unittest.skipUnless(
        condition=cuda_available, reason="This test needs a GPU host to run."
    )
    def test_fsdp_pytorch_version(self) -> None:
        """
        Test that a RuntimeError is thrown when using FSDP, and PyTorch < v1.12
        """
        spawn_multi_process(
            2,
            "nccl",
            self._test_fsdp_pytorch_version,
        )

    @staticmethod
    def _test_fsdp_pytorch_version() -> None:
        device = init_from_env()
        module = torch.nn.Linear(2, 2).to(device)

        tc = unittest.TestCase()
        with patch(
            "torchtnt.utils.prepare_module.is_torch_version_geq_1_12",
            return_value=False,
        ), tc.assertRaisesRegex(
            RuntimeError,
            "Please install PyTorch 1.12 or higher to use FSDP: https://pytorch.org/get-started/locally/",
        ):
            _ = prepare_fsdp(module, device, FSDPStrategy())

    @staticmethod
    def _test_is_fsdp_module() -> None:
        model = torch.nn.Linear(1, 1)
        assert not _is_fsdp_module(model)
        model = FSDP(torch.nn.Linear(1, 1))
        assert _is_fsdp_module(model)
        model = torch.nn.Linear(1, 1)
        if is_torch_version_geq_2_0():
            fully_shard(model)
            assert _is_fsdp_module(model)

    @unittest.skipUnless(
        distributed_available, reason="Torch distributed is needed to run"
    )
    # pyre-fixme[56]: Pyre was not able to infer the type of argument
    #  `torch.cuda.is_available() and torch.cuda.device_count() > 2` to decorator
    #  factory `unittest.skipUnless`.
    @unittest.skipUnless(
        condition=cuda_available and torch.cuda.device_count() >= 2,
        reason="This test needs 2 GPUs to run.",
    )
    def test_is_fsdp_module(self) -> None:
        spawn_multi_process(
            2,
            "gloo",
            self._test_is_fsdp_module,
        )

    @unittest.skipUnless(
        distributed_available, reason="Torch distributed is needed to run"
    )
    @unittest.skipUnless(
        condition=cuda_available, reason="This test needs a GPU host to run."
    )
    def test_fdsp_precision(self) -> None:
        spawn_multi_process(
            2,
            "nccl",
            self._test_fdsp_precision,
        )

    @staticmethod
    def _test_fdsp_precision() -> None:
        module = torch.nn.Linear(1, 1)
        device = init_from_env()
        mixed_precision = MixedPrecision(
            param_dtype=torch.float64,
        )
        fsdp_module = prepare_fsdp(
            module, device, FSDPStrategy(mixed_precision=mixed_precision)
        )
        tc = unittest.TestCase()
        tc.assertTrue(isinstance(fsdp_module, FSDP))
        tc.assertEqual(
            fsdp_module.mixed_precision.param_dtype, mixed_precision.param_dtype
        )

    # test strategy options
    def test_prepare_module_strategy_invalid_str(self) -> None:
        """
        Test that an exception is raised with an invalid strategy string
        """

        with self.assertRaisesRegex(ValueError, "Strategy foo not supported"):
            prepare_module(
                module=torch.nn.Linear(2, 2),
                device=init_from_env(),
                strategy="foo",
            )

    @unittest.skipUnless(
        distributed_available, reason="Torch distributed is needed to run"
    )
    @unittest.skipUnless(
        condition=cuda_available, reason="This test needs a GPU host to run."
    )
    def test_prepare_module_with_fsdp(self) -> None:
        """
        Launch tests of FSDP strategy
        """
        spawn_multi_process(
            2,
            "nccl",
            self._test_prepare_module_fsdp_strategy_wrapped_in_fsdp,
        )
        spawn_multi_process(
            2,
            "nccl",
            self._test_prepare_module_fsdp_string_wrapped_in_fsdp,
        )
        spawn_multi_process(
            2,
            "nccl",
            self._test_stochastic_weight_averaging_with_fsdp_raises,
        )

    @staticmethod
    def _test_prepare_module_fsdp_strategy_wrapped_in_fsdp() -> None:
        """
        Test that the module is correctly wrapped in FSDP
        """

        fsdp_module = prepare_module(
            module=torch.nn.Linear(2, 2),
            device=init_from_env(),
            strategy=FSDPStrategy(),
        )
        tc = unittest.TestCase()

        tc.assertTrue(isinstance(fsdp_module, FSDP))

    @staticmethod
    def _test_prepare_module_fsdp_string_wrapped_in_fsdp() -> None:
        """
        Test that the module is correctly wrapped in FSDP when passing "fsdp" as a string
        """

        fsdp_module = prepare_module(
            module=torch.nn.Linear(2, 2),
            device=init_from_env(),
            strategy="fsdp",
        )
        tc = unittest.TestCase()

        tc.assertTrue(isinstance(fsdp_module, FSDP))

    @staticmethod
    def _test_stochastic_weight_averaging_with_fsdp_raises() -> None:
        """
        Test that a RuntimeError is thrown when attempting to use Stochastic Weight Averaging and FSDP
        """

        tc = unittest.TestCase()
        with tc.assertRaisesRegex(
            RuntimeError,
            "Stochastic Weight Averaging is currently not supported with the FSDP strategy",
        ):
            prepare_module(
                module=torch.nn.Linear(2, 2),
                device=init_from_env(),
                strategy=FSDPStrategy(),
                swa_params=SWAParams(epoch_start=1, anneal_epochs=5),
            )

    @unittest.skipUnless(
        distributed_available, reason="Torch distributed is needed to run"
    )
    def test_prepare_module_with_ddp(self) -> None:
        """
        Launch tests of DDP strategy
        """

        spawn_multi_process(
            2,
            "gloo",
            self._test_prepare_module_ddp_strategy_wrapped_in_ddp,
        )
        spawn_multi_process(
            2,
            "gloo",
            self._test_prepare_module_ddp_string_wrapped_in_ddp,
        )
        spawn_multi_process(
            2,
            "gloo",
            self._test_prepare_module_ddp_throws_with_compile_params_and_static_graph,
        )

    @staticmethod
    def _test_prepare_module_ddp_strategy_wrapped_in_ddp() -> None:
        """
        Test that the module is correctly wrapped in DDP
        """

        ddp_module = prepare_module(
            module=torch.nn.Linear(2, 2),
            device=init_from_env(),
            strategy=DDPStrategy(),
        )
        tc = unittest.TestCase()

        tc.assertTrue(isinstance(ddp_module, DDP))

    @staticmethod
    def _test_prepare_module_ddp_string_wrapped_in_ddp() -> None:
        """
        Test that the module is correctly wrapped in DDP when passing "ddp" as a string
        """

        ddp_module = prepare_module(
            module=torch.nn.Linear(2, 2),
            device=init_from_env(),
            strategy="ddp",
        )
        tc = unittest.TestCase()

        tc.assertTrue(isinstance(ddp_module, DDP))

    @staticmethod
    def _test_prepare_module_ddp_throws_with_compile_params_and_static_graph() -> None:
        """
        Test that we throw an exception when we are using DDP static graph with compile params
        """

        tc = unittest.TestCase()
        with tc.assertRaisesRegex(
            RuntimeError,
            "Torch compile requires DDPStrategy's static_graph to be False",
        ):
            prepare_module(
                module=torch.nn.Linear(2, 2),
                device=init_from_env(),
                strategy=DDPStrategy(static_graph=True),
                torch_compile_params=TorchCompileParams(backend="inductor"),
            )

    @unittest.skipUnless(
        condition=COMPILE_AVAIL,
        reason="This test needs PyTorch 1.13 or greater to run.",
    )
    @unittest.skipUnless(
        condition=cuda_available, reason="This test needs a GPU host to run."
    )
    def test_prepare_module_compile_module_state_dict(self) -> None:
        device = init_from_env()
        my_module = torch.nn.Linear(2, 2, device=device)
        my_module_state_dict = my_module.state_dict()
        self.assertIsNone(my_module._compiled_call_impl)
        compiled_module = prepare_module(
            module=my_module,
            device=device,
            torch_compile_params=TorchCompileParams(backend="inductor"),
        )
        compiled_state_dict = compiled_module.state_dict()
        self.assertCountEqual(compiled_state_dict.keys(), my_module_state_dict.keys())
        for k in compiled_state_dict.keys():
            self.assertTrue(
                torch.allclose(my_module_state_dict[k], compiled_state_dict[k])
            )
        self.assertIsNotNone(compiled_module._compiled_call_impl)

    @unittest.skipUnless(
        condition=COMPILE_AVAIL,
        reason="This test needs PyTorch 1.13 or greater to run.",
    )
    def test_prepare_module_compile_invalid_backend(self) -> None:
        """
        verify error is thrown on invalid backend
        """

        with self.assertRaises(Exception):
            prepare_module(
                module=torch.nn.Linear(2, 2),
                device=init_from_env(),
                torch_compile_params=TorchCompileParams(backend="foo"),
            )

    def test_prepare_module_incompatible_FSDP_torchcompile_params(self) -> None:
        """
        verify error is thrown when FSDP's use_orig_params and torch compile is enabled
        """

        with self.assertRaises(RuntimeError):
            prepare_module(
                module=torch.nn.Linear(2, 2),
                device=init_from_env(),
                strategy=FSDPStrategy(use_orig_params=False),
                torch_compile_params=TorchCompileParams(),
            )
