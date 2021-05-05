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
# The Original Code is Copyright (C) 2020, TIALab, University of Warwick
# All rights reserved.
# ***** END GPL LICENSE BLOCK *****

"""Miscellaneous utilities which operate on image data."""
import warnings
from typing import Tuple, Union

import numpy as np
import cv2
from PIL import Image

from tiatoolbox.utils.transforms import bounds2locsize, imresize
from tiatoolbox.utils.misc import conv_out_size


PADDING_TO_BOUNDS = np.array([-1, -1, 1, 1])
"""
Constant array which when multiplied with padding and added to bounds,
applies the padding to the bounds.
"""
# Make this immutable / non-writable
PADDING_TO_BOUNDS.flags.writeable = False


def normalise_padding_size(padding):
    """Normalises padding to be length 4 (left, top, right, bottom).

    Given a scalar value, this is assumed to apply to all sides and
    therefore repeated for each output (left, right, top, bottom). A
    length 2 input is assumed to apply the same padding to the
    left/right and top/bottom.

    Args:
        padding (int or tuple(int)): Padding to normalise.

    Raises:
        ValueError: Invalid input size of padding (e.g. length 3).
        ValueError: Invalid input shape of padding (e.g. 3 dimensional).

    Returns:
        :class:`numpy.ndarray`: Numpy array of length 4 with elements containing
            padding for left, top, right, bottom.

    """
    padding_shape = np.shape(padding)
    if len(padding_shape) > 1:
        raise ValueError(
            "Invalid input padding shape. Must be scalar or 1 dimentional."
        )
    padding_size = np.size(padding)
    if padding_size == 3:
        raise ValueError("Padding has invalid size 3. Valid sizes are 1, 2, or 4.")

    if padding_size == 1:
        padding = np.repeat(padding, 4)
    elif padding_size == 2:
        padding = np.tile(padding, 2)
    else:
        padding = np.array(padding)
    return padding


def make_bounds_size_positive(bounds):
    """Make bounds have positive size and get horizontal/vertical flip flags.

    Bounds with a negative size in either direction with have the
    coordinates swapped (e.g. left and right or top and bottom swapped)
    and a respective horizontal or vertical flip flag set in the
    output to reflect the swaps which occurred.

    Args:
        bounds (:class:`numpy.ndarray`): Length 4 array of bounds.

    Returns:
        tuple: Three tuple containing positive bounds and flips:
            - :class:`numpy.ndarray` - Positive bounds
            - :py:obj:`bool` - Horizontal flip
            - :py:obj:`bool` - Vertical flip

    """
    hflip, vflip = False, False
    _, (width, height) = bounds2locsize(bounds)
    if width >= 0 and height >= 0:
        return bounds, hflip, vflip
    l, t, r, b = bounds
    if width < 0:
        l, r = r, l
        hflip = True
    if height < 0:
        t, b = b, t
        vflip = True
    bounds = np.array([l, t, r, b])
    return (bounds, hflip, vflip)


def crop_and_pad_edges(
    bounds: Tuple[int, int, int, int],
    max_dimensions: Tuple[int, int],
    region: np.ndarray,
    pad_mode: str = "constant",
    pad_constant_values: Union[int, Tuple] = 0,
) -> np.ndarray:
    """Apply padding to areas of a region which are outside max dimensions.

    Applies padding to areas of the image region which have coordinates
    less than zero or above the width and height in `max_dimensions`.
    Note that bounds and max_dimensions must given for the same image
    pyramid level (or more generally resolution e.g. if interpolated
    between levels or working in other units).

    Note: This function is planned to be deprecated in the future when a
    transition from OpenSlide to tifffile as a dependency is complete.
    It is currently used to remove padding from OpenSlide regions before
    applying custom padding via :func:`numpy.pad`. This allows the
    behaviour when reading OpenSlide images to be consistent with other
    formats.

    Args:
        bounds (tuple(int)): Bounds of the image region.
        max_dimensions (tuple(int)): The maximum valid x and y
            values of the bounds, i.e. the width and height of the
            slide.
        region (:class:`numpy.ndarray`): The image region to be cropped
            and padded.
        pad_mode (str): The pad mode to use, see :func:`numpy.pad`
            for valid pad modes. Defaults to 'constant'.
        pad_constant_values (int or tuple(int)): Constant value(s)
            to use when padding. Only used with pad_mode constant.

    Returns:
        :class:`numpy.ndarray`: The cropped and padded image.

    """
    left, top, right, bottom = bounds
    _, (bounds_width, bounds_height) = bounds2locsize(bounds)
    slide_width, slide_height = max_dimensions

    if slide_width < 0 or slide_height < 0:
        raise ValueError("max_dimensions must be >= 0.")

    if bounds_width <= 0 or bounds_height <= 0:
        raise ValueError("Bounds must have size (width and height) > 0.")

    # Create value ranges across x and y coordinates
    X, Y = np.arange(left, right), np.arange(top, bottom)
    # Find padding before (also the crop start index)
    x_before = np.argmin(np.abs(X))
    y_before = np.argmin(np.abs(Y))
    # Find the end index of the crop
    x_end = np.argmin(np.abs(slide_width - 1 - X))
    y_end = np.argmin(np.abs(slide_height - 1 - Y))
    # Find padding after the cropped sub-region
    x_after = bounds_width - 1 - x_end
    y_after = bounds_height - 1 - y_end
    # Full padding tuple for np.pad
    padding = (
        (y_before, y_after),
        (x_before, x_after),
    )

    # If no padding is required then return the original image unmodified
    if np.all(np.array(padding) == 0):
        return region

    # Add extra padding dimension for colour channels
    if len(region.shape) > 2:
        padding = padding + ((0, 0),)

    # Crop the region
    crop = region[y_before : y_end + 1, x_before : x_end + 1, ...]

    # Pad the region and return
    if pad_mode == "constant":
        return np.pad(crop, padding, mode=pad_mode, constant_values=pad_constant_values)
    return np.pad(crop, padding, mode=pad_mode)


def safe_padded_read(
    image,
    bounds,
    stride=1,
    padding=0,
    pad_mode="constant",
    pad_constant_values=0,
    pad_kwargs=None,
):
    """Read a region of a numpy array with padding applied to edges.

    Safely 'read' regions, even outside of the image bounds. Accepts
    integer bounds only.

    Regions outside of the source image are padded using
    any of the pad modes available in :func:`numpy.pad`.

    Note that padding of the output is not guarenteed to be
    integer/pixel aligned if using a stride != 1.

    .. figure:: images/out_of_bounds_read.png
            :width: 512
            :alt: Illustration for reading a region with negative
                coordinates using zero padding and reflection padding.

    Args:
        image (:class:`numpy.ndarray` or :class:`glymur.Jp2k`):
            Input image to read from.
        bounds (tuple(int)):
            Bounds of the region in (left, top,
            right, bottom) format.
        stride (int or tuple(int)):
            Stride when reading from img. Defaults to 1. A tuple is
            interpreted as stride in x and y (axis 1 and 0 respectively).
            Also applies to padding.
        padding (int or tuple(int)):
            Padding to apply to each bound. Default to 0.
        pad_mode (str):
            Method for padding when reading areas outside of
            the input image. Default is constant (0 padding). Possible
            values are: constant, reflect, wrap, symmetric. See
            :func:`numpy.pad` for more.
        pad_constant_values (int, tuple(int)): Constant values to use
            when padding with constant pad mode. Passed to the
            :func:`numpy.pad` `constant_values` argument. Default is 0.
        pad_kwargs (dict):
            Arbitrary keyword arguments passed through to the
            padding function :func:`numpy.pad`.

    Returns:
        numpy.ndarray: Padded image region.

    Raises:
        ValueError: Bounds must be integers.
        ValueError: Padding can't be negative.

    Examples:
        >>> bounds = (-5, -5, 5, 5)
        >>> safe_padded_read(img, bounds)

        >>> bounds = (-5, -5, 5, 5)
        >>> safe_padded_read(img, bounds, pad_mode="reflect")

        >>> bounds = (1, 1, 6, 6)
        >>> safe_padded_read(img, bounds, padding=2, pad_mode="reflect")

    """
    if pad_kwargs is None:
        pad_kwargs = {}
    if pad_mode == "constant" and "constant_values" not in pad_kwargs:
        pad_kwargs["constant_values"] = pad_constant_values

    padding = np.array(padding)
    # Ensure the bounds are integers.
    if not issubclass(np.array(bounds).dtype.type, (int, np.integer)):
        raise ValueError("Bounds must be integers.")

    if np.any(padding < 0):
        raise ValueError("Padding cannot be negative.")

    # Allow padding to be a 2-tuple in addition to an int or 4-tuple
    padding = normalise_padding_size(padding)

    # Ensure stride is a 2-tuple
    if np.size(stride) not in [1, 2]:
        raise ValueError("Stride must be of size 1 or 2.")
    if np.size(stride) == 1:
        stride = np.tile(stride, 2)
    x_stride, y_stride = stride

    # Check if the padded coords outside of the image bounds
    # (over the width/height or under 0)
    padded_bounds = bounds + (padding * np.array([-1, -1, 1, 1]))
    _, bounds_size = bounds2locsize(padded_bounds)
    out_size = tuple(conv_out_size(bounds_size, stride=stride))
    img_size = np.array(image.shape[:2][::-1])
    hw_limits = np.tile(img_size, 2)  # height/width limits
    zeros = np.zeros(hw_limits.shape)
    # If all original bounds are within the bounds
    padded_over = padded_bounds >= hw_limits
    padded_under = padded_bounds < zeros
    # If all padded coords are within the image then read normally
    if not any(padded_over | padded_under):
        l, t, r, b = padded_bounds
        return image[t:b:y_stride, l:r:x_stride, ...]
    # Else find the closest coordinates which are inside the image
    clamped_bounds = np.max([np.min([padded_bounds, hw_limits], axis=0), zeros], axis=0)
    clamped_bounds = np.round(clamped_bounds).astype(int)
    # Read the area within the image
    l, t, r, b = clamped_bounds
    region = image[t:b:y_stride, l:r:x_stride, ...]
    # Reduce bounds an img_size for the stride
    if not np.all(np.isin(stride, [None, 1])):
        # This if is not required but avoids unnecessary calculations
        bounds = conv_out_size(np.array(bounds), stride=np.tile(stride, 2))
        padded_bounds = bounds + (padding * np.array([-1, -1, 1, 1]))
        img_size = conv_out_size(img_size, stride=stride)
    # Find how much padding needs to be applied to fill the edge gaps
    # edge_padding = np.abs(padded_bounds - clamped_bounds)
    edge_padding = padded_bounds - np.array(
        [
            *np.min([[0, 0], padded_bounds[2:]], axis=0),
            *np.max([img_size, padded_bounds[:2] - img_size], axis=0),
        ]
    )
    edge_padding[:2] = np.min([edge_padding[:2], [0, 0]], axis=0)
    edge_padding[2:] = np.max([edge_padding[2:], [0, 0]], axis=0)
    edge_padding = np.abs(edge_padding)
    l, t, r, b = edge_padding
    pad_width = [(t, b), (l, r)]
    if len(region.shape) == 3:
        pad_width += [(0, 0)]
    # Pad the image region at the edges
    region = np.pad(
        region,
        pad_width,
        mode=pad_mode,
        **pad_kwargs,
    )
    if region.shape[:2] != out_size[::-1]:
        region = cv2.resize(region, out_size, interpolation=cv2.INTER_LINEAR)
    return region


def sub_pixel_read(
    image,
    bounds,
    output_size,
    padding=0,
    stride=1,
    interpolation="nearest",
    pad_at_baseline=False,
    read_func=None,
    pad_mode="constant",
    pad_constant_values=0,
    read_kwargs=None,
):
    """Read and resize an image region with sub-pixel bounds.
    Allows for reading of image regions with sub-pixel coordinates, and
    out of bounds reads with various padding and interpolation modes.

    .. figure:: images/sub_pixel_reads.png
            :width: 512
            :alt: Illustration for reading a region with fractional
                coordinates (sub-pixel).
    Args:
        image (:class:`numpy.ndarray`):
            Image to read from.
        bounds (tuple(float)):
            Bounds of the image to read in
            (left, top, right, bottom) format.
        output_size (tuple(int)):
            The desired output size.
        padding (int or tuple(int)):
            Amount of padding to apply to the image region in pixels.
            Defaults to 0.
        stride (int or tuple(int)):
            Stride when reading from img. Defaults to 1. A tuple is
            interpreted as stride in x and y (axis 1 and 0 respectively).
        interpolation (str):
            Method of interpolation. Possible values are: nearest,
            linear, cubic, lanczos, area. Defaults to nearest.
        pad_at_baseline (bool):
            Apply padding in terms of baseline
            pixels. Defaults to False, meaning padding is added to the
            output image size in pixels.
        read_func (collections.abc.Callable):
            Custom read function. Defaults to
            :func:`safe_padded_read`. A function which recieves
            two positional args of the image object and a set of
            integer bounds in addition to padding key word arguments
            for reading a pixel-aligned bounding region. This function
            should return a numpy array with 2 or 3 dimensions. See
            examples for more.
        pad_mode (str):
            Method for padding when reading areas outside of
            the input image. Default is constant (0 padding). This is
            passed to `read_func` which defaults to
            :func:`safe_padded_read`. See :func:`safe_padded_read`
            for supported pad modes.
        **read_kwargs (dict):
            Arbitrary keyword arguments passed through to `read_func`.
    Return:
        :class:`numpy.ndimage`: Output image region.

    Raises:
        ValueError: Invalid arguments.
        AssertionError: Internal errors, possibly due to invalid values.
    Examples:
        Simple read:
        >>> bounds = (0, 0, 10.5, 10.5)
        >>> sub_pixel_read(image, bounds)
        Read with padding applied to bounds before reading:
        >>> bounds = (0, 0, 10.5, 10.5)
        >>> region = sub_pixel_read(
        ...     image,
        ...     bounds,
        ...     padding=2,
        ...     pad_mode="reflect",
        ... )
        Read with padding applied after reading:
        >>> bounds = (0, 0, 10.5, 10.5)
        >>> region = sub_pixel_read(image, bounds)
        >>> region = np.pad(region, padding=2, mode="reflect")

        Custom read function which generates a diagonal gradient:
        >>> bounds = (0, 0, 10.5, 10.5)
        >>> def gradient(_, b, **kw):
        ...     width, height = (b[2] - b[0], b[3] - b[1])
        ...     return np.mgrid[:height, :width].sum(0)
        >>> sub_pixel_read(bounds, read_func=gradient)
        Custom read function which gets pixel data from a custom object:
        >>> bounds = (0, 0, 10, 10)
        >>> def openslide_read(image, bounds, **kwargs):
        ...     # Note that bounds may contain negative integers
        ...     left, top, right, bottom = bounds
        ...     size = (right - left, bottom - top)
        ...     pil_img = image.read_region((left, top), level=0, size=size)
        ...     return np.array(pil_img.convert("RGB"))
        >>> sub_pixel_read(bounds, read_func=openslide_read)

    """
    if read_kwargs is None:
        read_kwargs = {}

    if isinstance(image, Image.Image):
        image = np.array(image)
    bounds = np.array(bounds)
    _, bounds_size = bounds2locsize(bounds)
    if np.size(stride) == 1:
        stride = np.tile(stride, 2)
    bounds_size = bounds_size / stride
    if 0 in bounds_size:
        raise ValueError("Bounds must have non-zero size in each dimension")
    scale_factor = np.abs(output_size / bounds_size)

    # Normalise desired padding to be a length 4 array.
    padding = normalise_padding_size(padding)

    # Divide padding by scale factor to get padding to add to bounds.
    if pad_at_baseline:
        bounds_padding = padding
        output_padding = padding * np.tile(scale_factor, 2)
    else:
        bounds_padding = padding / np.tile(scale_factor, 2)
        output_padding = padding

    padded_output_size = np.round(output_size + output_padding.reshape(2, 2).sum(0))

    # Find the pixel-aligned indexes to read the image at
    padded_bounds = bounds + (bounds_padding * PADDING_TO_BOUNDS)

    # The left/start_x and top/start_y values should usually be smaller
    # than the right/end_x and bottom/end_y values.
    padded_bounds, hflip, vflip = make_bounds_size_positive(padded_bounds)
    if hflip or vflip:
        warnings.warn("Bounds have a negative size, output will be flipped.")

    pixel_aligned_bounds = padded_bounds.copy()
    pixel_aligned_bounds[:2] = np.floor(pixel_aligned_bounds[:2])
    pixel_aligned_bounds[2:] = np.ceil(pixel_aligned_bounds[2:])
    pixel_aligned_bounds = pixel_aligned_bounds.astype(int)
    # Keep the difference between pixel-aligned and original coordinates
    residuals = padded_bounds - pixel_aligned_bounds

    # If no read function is given, use the default.
    if read_func is None:
        read_func = safe_padded_read

    _, pixel_aligned_size = bounds2locsize(pixel_aligned_bounds)
    if any(pixel_aligned_size <= 0):
        raise ValueError("Bounds have zero size after padding and integer alignment.")

    # Perform the pixel-aligned read.
    region = read_func(
        image,
        pixel_aligned_bounds,
        pad_mode=pad_mode,
        stride=stride,
        pad_constant_values=pad_constant_values,
        **read_kwargs,
    )

    # Error checking
    region_size = np.array(region.shape[:2][::-1])
    if not np.all(region_size > 0):
        raise ValueError("Region returned from read_func is empty.")

    if any(region_size != conv_out_size(pixel_aligned_size, stride=stride)):
        raise ValueError("Read func returned region of incorrect size.")

    # Find the size which the region should be scaled to.
    scaled_size = region_size * scale_factor
    scaled_size = tuple(scaled_size.astype(int))

    # If no interpolation is to be used, return the region without resampling
    if interpolation == "none":
        return region

    # Resize/scale the region and residuals
    scaled_region = imresize(
        region, output_size=scaled_size, interpolation=interpolation
    )
    scaled_residuals = residuals * np.tile(scale_factor, 2)

    # Trim extra whole pixels (residuals) which resulted from expanding
    # to integers before scaling.
    resized_indexes = scaled_residuals.astype(int)
    resized_indexes += np.array([0, 0, *scaled_size])
    l, t, r, b = resized_indexes
    result = scaled_region[t:b, l:r, ...]
    result_size = np.array(result.shape[:2][::-1])

    # Re-sample to fit in the requested output size (to fix 1px differences)
    if not all(result_size == padded_output_size):
        # raise Exception
        result = cv2.resize(
            result, tuple(padded_output_size), interpolation=cv2.INTER_LINEAR
        )

    # Apply flips
    if hflip:
        result = np.flipud(result)
    if vflip:
        result = np.fliplr(result)

    return result