# Copyright The PyTorch Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import operator
import os
from collections import namedtuple
from unittest import mock
from unittest.mock import patch

import pytest
import torch

import tests_pytorch.helpers.pipelines as tpipes
import tests_pytorch.helpers.utils as tutils
from pytorch_lightning import Trainer
from pytorch_lightning.accelerators import CPUAccelerator, GPUAccelerator
from pytorch_lightning.demos.boring_classes import BoringModel
from pytorch_lightning.plugins.environments import TorchElasticEnvironment
from pytorch_lightning.utilities import device_parser
from pytorch_lightning.utilities.exceptions import MisconfigurationException
from pytorch_lightning.utilities.imports import _compare_version, _TORCHTEXT_LEGACY
from tests_pytorch.helpers.datamodules import ClassifDataModule
from tests_pytorch.helpers.imports import Batch, Dataset, Example, Field, LabelField
from tests_pytorch.helpers.runif import RunIf
from tests_pytorch.helpers.simple_models import ClassificationModel

PL_VERSION_LT_1_5 = _compare_version("pytorch_lightning", operator.lt, "1.5")
PRETEND_N_OF_GPUS = 16


@RunIf(min_cuda_gpus=2)
def test_multi_gpu_none_backend(tmpdir):
    """Make sure when using multiple GPUs the user can't use `accelerator = None`."""
    tutils.set_random_main_port()
    trainer_options = dict(
        default_root_dir=tmpdir,
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=0.2,
        limit_val_batches=0.2,
        accelerator="gpu",
        devices=2,
    )

    dm = ClassifDataModule()
    model = ClassificationModel()
    tpipes.run_model_test(trainer_options, model, dm)


@RunIf(min_cuda_gpus=2)
@pytest.mark.parametrize("devices", [1, [0], [1]])
def test_single_gpu_model(tmpdir, devices):
    """Make sure single GPU works (DP mode)."""
    trainer_options = dict(
        default_root_dir=tmpdir,
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=0.1,
        limit_val_batches=0.1,
        accelerator="gpu",
        devices=devices,
    )

    model = BoringModel()
    tpipes.run_model_test(trainer_options, model)


@pytest.fixture
def mocked_device_count(monkeypatch):
    def device_count():
        return PRETEND_N_OF_GPUS

    def is_available():
        return True

    monkeypatch.setattr(torch.cuda, "is_available", is_available)
    monkeypatch.setattr(torch.cuda, "device_count", device_count)


@pytest.fixture
def mocked_device_count_0(monkeypatch):
    def device_count():
        return 0

    monkeypatch.setattr(torch.cuda, "device_count", device_count)


# Asking for a gpu when non are available will result in a MisconfigurationException
@pytest.mark.parametrize(
    ["devices", "expected_root_gpu", "strategy"],
    [
        (1, None, "ddp"),
        (3, None, "ddp"),
        (3, None, "ddp"),
        ([1, 2], None, "ddp"),
        ([0, 1], None, "ddp"),
        (-1, None, "ddp"),
        ("-1", None, "ddp"),
    ],
)
def test_root_gpu_property_0_raising(mocked_device_count_0, devices, expected_root_gpu, strategy):
    with pytest.raises(MisconfigurationException):
        Trainer(accelerator="gpu", devices=devices, strategy=strategy)


@pytest.mark.parametrize(
    ["devices", "expected_root_gpu"],
    [
        pytest.param(None, None, id="No gpus, expect gpu root device to be None"),
        pytest.param([0], 0, id="Oth gpu, expect gpu root device to be 0."),
        pytest.param([1], 1, id="1st gpu, expect gpu root device to be 1."),
        pytest.param([3], 3, id="3rd gpu, expect gpu root device to be 3."),
        pytest.param([1, 2], 1, id="[1, 2] gpus, expect gpu root device to be 1."),
    ],
)
def test_determine_root_gpu_device(devices, expected_root_gpu):
    assert device_parser.determine_root_gpu_device(devices) == expected_root_gpu


@pytest.mark.parametrize(
    ["devices", "expected_gpu_ids"],
    [
        (None, None),
        (0, None),
        ([], None),
        (1, [0]),
        (3, [0, 1, 2]),
        pytest.param(-1, list(range(PRETEND_N_OF_GPUS)), id="-1 - use all gpus"),
        ([0], [0]),
        ([1, 3], [1, 3]),
        ((1, 3), [1, 3]),
        ("0", None),
        ("3", [0, 1, 2]),
        ("1, 3", [1, 3]),
        ("2,", [2]),
        pytest.param("-1", list(range(PRETEND_N_OF_GPUS)), id="'-1' - use all gpus"),
    ],
)
def test_parse_gpu_ids(mocked_device_count, devices, expected_gpu_ids):
    assert device_parser.parse_gpu_ids(devices) == expected_gpu_ids


@pytest.mark.parametrize("devices", [0.1, -2, False, [-1], [None], ["0"], [0, 0]])
def test_parse_gpu_fail_on_unsupported_inputs(mocked_device_count, devices):
    with pytest.raises(MisconfigurationException):
        device_parser.parse_gpu_ids(devices)


@pytest.mark.parametrize("devices", [[1, 2, 19], -1, "-1"])
def test_parse_gpu_fail_on_non_existent_id(mocked_device_count_0, devices):
    with pytest.raises(MisconfigurationException):
        device_parser.parse_gpu_ids(devices)


def test_parse_gpu_fail_on_non_existent_id_2(mocked_device_count):
    with pytest.raises(MisconfigurationException):
        device_parser.parse_gpu_ids([1, 2, 19])


@pytest.mark.parametrize("devices", [-1, "-1"])
def test_parse_gpu_returns_none_when_no_devices_are_available(mocked_device_count_0, devices):
    with pytest.raises(MisconfigurationException):
        device_parser.parse_gpu_ids(devices)


@mock.patch.dict(
    os.environ,
    {
        "CUDA_VISIBLE_DEVICES": "0",
        "LOCAL_RANK": "1",
        "GROUP_RANK": "1",
        "RANK": "3",
        "WORLD_SIZE": "4",
        "LOCAL_WORLD_SIZE": "2",
        "TORCHELASTIC_RUN_ID": "1",
    },
)
@mock.patch("torch.cuda.device_count", return_value=1)
@mock.patch("torch.cuda.is_available", return_value=True)
@pytest.mark.parametrize("gpus", [[0, 1, 2], 2, "0", [0, 2]])
def test_torchelastic_gpu_parsing(mocked_device_count, mocked_is_available, gpus):
    """Ensure when using torchelastic and nproc_per_node is set to the default of 1 per GPU device That we omit
    sanitizing the gpus as only one of the GPUs is visible."""
    with pytest.deprecated_call(match=r"is deprecated in v1.7 and will be removed in v2.0."):
        trainer = Trainer(gpus=gpus)
    assert isinstance(trainer._accelerator_connector.cluster_environment, TorchElasticEnvironment)
    # when use gpu
    if device_parser.parse_gpu_ids(gpus) is not None:
        assert isinstance(trainer.accelerator, GPUAccelerator)
        assert trainer.num_devices == len(gpus) if isinstance(gpus, list) else gpus
        assert trainer.device_ids == device_parser.parse_gpu_ids(gpus)
    # fall back to cpu
    else:
        assert isinstance(trainer.accelerator, CPUAccelerator)
        assert trainer.num_devices == 1
        assert trainer.device_ids == [0]


@RunIf(min_cuda_gpus=1)
def test_single_gpu_batch_parse():
    trainer = Trainer(accelerator="gpu", devices=1)

    # non-transferrable types
    primitive_objects = [None, {}, [], 1.0, "x", [None, 2], {"x": (1, 2), "y": None}]
    for batch in primitive_objects:
        data = trainer.strategy.batch_to_device(batch, torch.device("cuda:0"))
        assert data == batch

    # batch is just a tensor
    batch = torch.rand(2, 3)
    batch = trainer.strategy.batch_to_device(batch, torch.device("cuda:0"))
    assert batch.device.index == 0 and batch.type() == "torch.cuda.FloatTensor"

    # tensor list
    batch = [torch.rand(2, 3), torch.rand(2, 3)]
    batch = trainer.strategy.batch_to_device(batch, torch.device("cuda:0"))
    assert batch[0].device.index == 0 and batch[0].type() == "torch.cuda.FloatTensor"
    assert batch[1].device.index == 0 and batch[1].type() == "torch.cuda.FloatTensor"

    # tensor list of lists
    batch = [[torch.rand(2, 3), torch.rand(2, 3)]]
    batch = trainer.strategy.batch_to_device(batch, torch.device("cuda:0"))
    assert batch[0][0].device.index == 0 and batch[0][0].type() == "torch.cuda.FloatTensor"
    assert batch[0][1].device.index == 0 and batch[0][1].type() == "torch.cuda.FloatTensor"

    # tensor dict
    batch = [{"a": torch.rand(2, 3), "b": torch.rand(2, 3)}]
    batch = trainer.strategy.batch_to_device(batch, torch.device("cuda:0"))
    assert batch[0]["a"].device.index == 0 and batch[0]["a"].type() == "torch.cuda.FloatTensor"
    assert batch[0]["b"].device.index == 0 and batch[0]["b"].type() == "torch.cuda.FloatTensor"

    # tuple of tensor list and list of tensor dict
    batch = ([torch.rand(2, 3) for _ in range(2)], [{"a": torch.rand(2, 3), "b": torch.rand(2, 3)} for _ in range(2)])
    batch = trainer.strategy.batch_to_device(batch, torch.device("cuda:0"))
    assert batch[0][0].device.index == 0 and batch[0][0].type() == "torch.cuda.FloatTensor"

    assert batch[1][0]["a"].device.index == 0
    assert batch[1][0]["a"].type() == "torch.cuda.FloatTensor"

    assert batch[1][0]["b"].device.index == 0
    assert batch[1][0]["b"].type() == "torch.cuda.FloatTensor"

    # namedtuple of tensor
    BatchType = namedtuple("BatchType", ["a", "b"])
    batch = [BatchType(a=torch.rand(2, 3), b=torch.rand(2, 3)) for _ in range(2)]
    batch = trainer.strategy.batch_to_device(batch, torch.device("cuda:0"))
    assert batch[0].a.device.index == 0
    assert batch[0].a.type() == "torch.cuda.FloatTensor"

    # non-Tensor that has `.to()` defined
    class CustomBatchType:
        def __init__(self):
            self.a = torch.rand(2, 2)

        def to(self, *args, **kwargs):
            self.a = self.a.to(*args, **kwargs)
            return self

    batch = trainer.strategy.batch_to_device(CustomBatchType(), torch.device("cuda:0"))
    assert batch.a.type() == "torch.cuda.FloatTensor"

    # torchtext.data.Batch
    if not _TORCHTEXT_LEGACY:
        return

    samples = [
        {"text": "PyTorch Lightning is awesome!", "label": 0},
        {"text": "Please make it work with torchtext", "label": 1},
    ]

    text_field = Field()
    label_field = LabelField()
    fields = {"text": ("text", text_field), "label": ("label", label_field)}

    examples = [Example.fromdict(sample, fields) for sample in samples]
    dataset = Dataset(examples=examples, fields=fields.values())

    # Batch runs field.process() that numericalizes tokens, but it requires to build dictionary first
    text_field.build_vocab(dataset)
    label_field.build_vocab(dataset)

    batch = Batch(data=examples, dataset=dataset)

    with pytest.deprecated_call(match="The `torchtext.legacy.Batch` object is deprecated"):
        batch = trainer.strategy.batch_to_device(batch, torch.device("cuda:0"))

    assert batch.text.type() == "torch.cuda.LongTensor"
    assert batch.label.type() == "torch.cuda.LongTensor"


@RunIf(min_cuda_gpus=1)
def test_non_blocking():
    """Tests that non_blocking=True only gets passed on torch.Tensor.to, but not on other objects."""
    trainer = Trainer()

    batch = torch.zeros(2, 3)
    with patch.object(batch, "to", wraps=batch.to) as mocked:
        batch = trainer.strategy.batch_to_device(batch, torch.device("cuda:0"))
        mocked.assert_called_with(torch.device("cuda", 0), non_blocking=True)

    class BatchObject:
        def to(self, *args, **kwargs):
            pass

    batch = BatchObject()
    with patch.object(batch, "to", wraps=batch.to) as mocked:
        batch = trainer.strategy.batch_to_device(batch, torch.device("cuda:0"))
        mocked.assert_called_with(torch.device("cuda", 0))
