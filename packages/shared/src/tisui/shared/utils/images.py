from __future__ import annotations

from PIL import Image


ImageSize = tuple[int, int]
BBox = list[int]

def _build_image_data_url(image: Image) -> str:
    image_bytes = image.get("image_bytes") or b""
    if not image_bytes:
        return ""

    image_format = str(image.get("image_format") or "").upper()
    mime_type = {
        "PNG": "image/png",
        "JPG": "image/jpeg",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
    }.get(image_format, "application/octet-stream")

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"

def _resize_to_max_side_size(
    width: int,
    height: int,
    *,
    max_side: int = 500,
) -> ImageSize:
    if width <= 0 or height <= 0:
        raise ValueError("width 和 height 必须大于 0")
    if max_side <= 0:
        raise ValueError("max_side 必须大于 0")

    longest_side = max(width, height)
    if longest_side <= max_side:
        return width, height

    ratio = max_side / float(longest_side)
    resized_width = max(1, int(round(width * ratio)))
    resized_height = max(1, int(round(height * ratio)))
    return resized_width, resized_height

def crop_image_bytes(
    image_bytes: bytes,
    bbox: BBox,
    output_format: str = "JPEG"
) -> bytes:
    """
    裁剪 bytes 格式的图片，返回裁剪后的 bytes
    
    Args:
        image_bytes: 原始图片的字节数据
        left, top, right, bottom: 裁剪区域坐标（左、上、右、下）
        output_format: 输出格式，可选 "JPEG", "PNG", "WEBP" 等
    
    Returns:
        裁剪后的图片字节数据
    """
    # 1. bytes → PIL Image 对象
    img = Image.open(io.BytesIO(image_bytes))
    left = bbox[0]
    top = bbox[1]
    right = bbox[2]
    bottom = bbox[3]
    # 2. 裁剪
    cropped = img.crop((left, top, right, bottom))
    
    # 3. PIL Image 对象 → bytes
    output_buffer = io.BytesIO()
    cropped.save(output_buffer, format=output_format)
    
    return output_buffer.getvalue()

def resize_image_by_max_side(
    image: Image.Image,
    *,
    max_side: int = 500,
    resample: int = Image.Resampling.LANCZOS,
) -> Image.Image:
    """
    按最长边等比压缩图片，并返回新的 Image.Image 对象。

    规则：以最长边作为缩放基准，等比缩放到最长边 <= max_side。

    Args:
        image: 输入图片（PIL.Image.Image）。
        max_side: 最长边上限，默认 500。
        resample: PIL 的采样算法，默认 LANCZOS。

    Returns:
        压缩后的新图片对象（Image.Image）。
    """
    resized_width, resized_height = _resize_to_max_side_size(
        image.width,
        image.height,
        max_side=max_side,
    )
    if resized_width == image.width and resized_height == image.height:
        return image.copy()
    return image.resize((resized_width, resized_height), resample=resample)


def generate_nine_grid_anchors(
    width: int,
    height: int,
) -> list[tuple[list[int], list[int]]]:
    """
    生成图片 9 宫格锚点（从上到下、从左到右），并返回每个宫格的左上/右下坐标。

    Returns 的结构（也即函数注解）为：
        list[tuple[list[int], list[int]]]
    其中每个元素表示一个宫格：
        ([x1, y1], [x2, y2])

    Args:
        width: 图片宽度。
        height: 图片高度。

    Returns:
        宫格列表（长度 9），顺序为 1~9：上左、上中、上右、中左、中中、中右、下左、下中、下右。
    """
    if width <= 0 or height <= 0:
        raise ValueError("width 和 height 必须大于 0")

    anchors: list[tuple[list[int], list[int]]] = []
    for row in range(3):
        y1 = int(height * row / 3)
        y2 = int(height * (row + 1) / 3)
        for col in range(3):
            x1 = int(width * col / 3)
            x2 = int(width * (col + 1) / 3)
            anchors.append(([x1, y1], [x2, y2]))
    return anchors


def generate_gride_auchors(
    rows: int,
    cols: int,
    width: int,
    height: int,
) -> list[list[tuple[list[int], list[int]]]]:
    """
    按指定矩阵行列切分图片，并返回锚点矩阵。

    每个锚点元素的结构为：
        ([x1, y1], [x2, y2])

    Args:
        rows: 矩阵行数。
        cols: 矩阵列数。
        width: 图片宽度。
        height: 图片高度。

    Returns:
        锚点二维矩阵，外层为行，内层为列。
    """
    if rows <= 0 or cols <= 0:
        raise ValueError("rows 和 cols 必须大于 0")
    if width <= 0 or height <= 0:
        raise ValueError("width 和 height 必须大于 0")

    anchor_matrix: list[list[tuple[list[int], list[int]]]] = []
    for row in range(rows):
        row_anchors: list[tuple[list[int], list[int]]] = []
        y1 = int(height * row / rows)
        y2 = int(height * (row + 1) / rows)
        for col in range(cols):
            x1 = int(width * col / cols)
            x2 = int(width * (col + 1) / cols)
            row_anchors.append(([x1, y1], [x2, y2]))
        anchor_matrix.append(row_anchors)
    return anchor_matrix


def _point_from_coord(
    coord: list[int] | tuple[list[int], list[int]],
) -> tuple[float, float]:
    if isinstance(coord, list):
        if len(coord) != 2:
            raise ValueError("坐标必须是 [x, y]")
        return float(coord[0]), float(coord[1])

    if (
        isinstance(coord, tuple)
        and len(coord) == 2
        and isinstance(coord[0], list)
        and isinstance(coord[1], list)
        and len(coord[0]) == 2
        and len(coord[1]) == 2
    ):
        x1, y1 = coord[0]
        x2, y2 = coord[1]
        return (float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0

    raise ValueError("坐标必须是 [x, y] 或 ([x1, y1], [x2, y2])")


def relative_to_absolute_coord(
    width: int,
    height: int,
    relative_coord: list[float],
    start_coord: list[int],
) -> list[int]:
    """
    基于相对坐标和起始坐标，换算为绝对坐标。

    当前按仓库内 relative_bbox 的约定处理：相对坐标为 0~1 之间的值。

    输入支持两种形式：
        [x, y]
        [x1, y1, x2, y2]

    计算规则：
        absolute_x = start_x + relative_x * width
        absolute_y = start_y + relative_y * height

    Args:
        width: 当前图片宽度。
        height: 当前图片高度。
        relative_coord: 相对坐标，支持点坐标或矩形坐标。
        start_coord: 起始绝对坐标 [start_x, start_y]。

    Returns:
        绝对坐标。输入为 [x, y] 时返回 [abs_x, abs_y]；
        输入为 [x1, y1, x2, y2] 时返回 [abs_x1, abs_y1, abs_x2, abs_y2]。
    """
    if width <= 0 or height <= 0:
        raise ValueError("width 和 height 必须大于 0")
    if len(start_coord) != 2:
        raise ValueError("start_coord 必须是 [x, y]")
    if len(relative_coord) not in (2, 4):
        raise ValueError("relative_coord 必须是 [x, y] 或 [x1, y1, x2, y2]")

    start_x, start_y = int(start_coord[0]), int(start_coord[1])

    if len(relative_coord) == 2:
        x = int(round(start_x + float(relative_coord[0]) * width))
        y = int(round(start_y + float(relative_coord[1]) * height))
        return [x, y]

    left = int(round(start_x + float(relative_coord[0]) * width))
    top = int(round(start_y + float(relative_coord[1]) * height))
    right = int(round(start_x + float(relative_coord[2]) * width))
    bottom = int(round(start_y + float(relative_coord[3]) * height))
    return [left, top, right, bottom]


def infer_element_position(
    width: int,
    height: int,
    coord: list[int] | tuple[list[int], list[int]],
) -> str:
    """
    基于 9 宫格锚点判断元素位置信息（内部会调用 generate_nine_grid_anchors）。

    输入可以是点坐标：
        [x, y]
    或矩形坐标：
        ([x1, y1], [x2, y2])
    当输入为矩形时，会自动取矩形中心点作为判断依据。

    Args:
        width: 图片宽度。
        height: 图片高度。
        coord: 点坐标或矩形坐标。

    Returns:
        位置字符串：左上 / 上中 / 右上 / 左中 / 中 / 右中 / 左下 / 下中 / 右下
    """
    if width <= 0 or height <= 0:
        raise ValueError("width 和 height 必须大于 0")

    x, y = _point_from_coord(coord)
    x = max(0.0, min(float(width), x))
    y = max(0.0, min(float(height), y))

    anchors = generate_nine_grid_anchors(width, height)
    labels = ["左上", "上中", "右上", "左中", "中", "右中", "左下", "下中", "右下"]

    for index, (left_top, right_bottom) in enumerate(anchors):
        x1, y1 = left_top
        x2, y2 = right_bottom

        in_x = (float(x1) <= x < float(x2)) or (x == float(width) and x2 == width and x >= float(x1))
        in_y = (float(y1) <= y < float(y2)) or (y == float(height) and y2 == height and y >= float(y1))
        if in_x and in_y:
            return labels[index]

    return labels[-1]

def auto_crop_jpeg_with_bbox(
    image_bytes: bytes, 
    threshold: int = 20
) -> Tuple[bytes, Tuple[int, int]]:
    """
    处理 JPEG 图片的自动裁剪，并返回裁剪区域的起始坐标
    
    Args:
        image_bytes: 原始图片的字节数据
        threshold: 白色判定阈值（0-255）
    
    Returns:
        (裁剪后的图片字节数据, (左上角x坐标, 左上角y坐标))
    """
    img = Image.open(io.BytesIO(image_bytes))
    original_size = img.size  # (width, height)
    
    img = img.convert('RGBA')
    data = img.getdata()
    
    # 将接近白色的像素设为透明
    new_data = []
    for item in data:
        if item[0] > 255 - threshold and item[1] > 255 - threshold and item[2] > 255 - threshold:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
    
    img.putdata(new_data)
    
    # 获取非透明区域的边界框
    bbox = img.getbbox()  # (left, top, right, bottom)
    
    if bbox:
        left, top, right, bottom = bbox
        cropped = img.crop(bbox)
        cropped = cropped.convert('RGB')
        
        output_buffer = io.BytesIO()
        cropped.save(output_buffer, format='JPEG')
        
        # 返回裁剪后的图片和起始坐标
        return output_buffer.getvalue(), (left, top)
    else:
        # 整张图都是空白，返回原图和 (0, 0)
        return image_bytes, (0, 0)

__all__ = [
    "generate_gride_auchors",
    "generate_nine_grid_anchors",
    "generate_nine_grid_relative_anchors",
    "infer_element_position",
    "relative_to_absolute_coord",
    "resize_image_by_max_side",
    "crop_image_bytes",
    "auto_crop_jpeg_with_bbox"
]
