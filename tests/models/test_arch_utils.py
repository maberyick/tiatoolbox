# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# The Original Code is Copyright (C) 2021, TIA Centre, University of Warwick
# All rights reserved.
# ***** END GPL LICENSE BLOCK *****

"""Unit test package for architecture utilities"""

import numpy as np
import pytest
import torch

from tiatoolbox.models.architecture.utils import (
    UpSample2x,
    centre_crop,
    centre_crop_to_shape,
)


def test_all():
    """Contains all tests for now."""
    layer = UpSample2x()
    sample = np.array([[1, 2], [3, 4]])[..., None]
    batch = torch.from_numpy(sample)[None]
    batch = batch.permute(0, 3, 1, 2).type(torch.float32)
    output = layer(batch).permute(0, 2, 3, 1)[0].numpy()
    _output = np.array(
        [
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [3, 3, 4, 4],
            [3, 3, 4, 4],
        ]
    )
    assert np.sum(_output - output) == 0

    #
    with pytest.raises(ValueError, match=r".*Unknown.*format.*"):
        centre_crop(_output[None, :, :, None], [2, 2], "NHWCT")

    x = centre_crop(_output[None, :, :, None], [2, 2], "NHWC")
    assert np.sum(x[0, :, :, 0] - sample) == 0
    x = centre_crop(_output[None, None, :, :], [2, 2], "NCHW")
    assert np.sum(x[0, 0, :, :] - sample) == 0


def test_centre_crop_operators():
    """Test for crop et. al. ."""
    sample = torch.rand((1, 3, 15, 15), dtype=torch.float32)
    output = centre_crop(sample, [3, 3], data_format="NCHW")
    assert torch.sum(output - sample[:, :, 1:13, 1:13]) == 0, f"{output.shape}"

    sample = torch.rand((1, 15, 15, 3), dtype=torch.float32)
    output = centre_crop(sample, [3, 3], data_format="NHWC")
    assert torch.sum(output - sample[:, 1:13, 1:13, :]) == 0, f"{output.shape}"

    # *
    x = torch.rand((1, 3, 15, 15), dtype=torch.float32)
    y = x[:, :, 6:9, 6:9]
    output = centre_crop_to_shape(x, y, data_format="NCHW")
    assert torch.sum(output - y) == 0, f"{output.shape}"

    x = torch.rand((1, 15, 15, 3), dtype=torch.float32)
    y = x[:, 6:9, 6:9, :]
    output = centre_crop_to_shape(x, y, data_format="NHWC")
    assert torch.sum(output - y) == 0, f"{output.shape}"

    with pytest.raises(ValueError, match=r".*Unknown.*format.*"):
        centre_crop_to_shape(x, y, data_format="NHWCT")

    x = torch.rand((1, 3, 15, 15), dtype=torch.float32)
    y = x[:, :, 6:9, 6:9]
    with pytest.raises(ValueError, match=r".*Height.*smaller than `y`*"):
        centre_crop_to_shape(y, x, data_format="NCHW")