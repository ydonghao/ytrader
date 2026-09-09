import hashlib
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
import requests


def save_download_file(file_byte, folder_name, filename):
    """
    Save an uploaded file to the specified folder with a hash of its content as the file name.
    """
    cache_path = Path("tmp")
    folder_path = cache_path / folder_name

    # Create the folder if it doesn't exist
    if not folder_path.exists():
        folder_path.mkdir(parents=True, exist_ok=True)

    # Create a hash of the file content
    sha256_hash = hashlib.sha256()
    sha256_hash.update(file_byte)

    # Use the hex digest of the hash as the file name
    hex_dig = sha256_hash.hexdigest()
    md5_name = hex_dig
    file_path = folder_path / f'{md5_name}_{filename}'
    if len(filename) > 60:
        file_path = folder_path / f'{md5_name}_{filename[-60:]}'
    with open(file_path, 'wb') as new_file:
        new_file.write(file_byte)
    return str(file_path)


def file_download(file_path: str):
    """download file and return path"""
    if not os.path.isfile(file_path) and _is_valid_url(file_path):
        r = requests.get(file_path, verify=False)

        if r.status_code != 200:
            raise ValueError('Check the url of your file; returned status code %s' % r.status_code)
        # 检查Content-Disposition头来找出文件名
        content_disposition = r.headers.get('Content-Disposition')
        filename = ''
        if content_disposition:
            filename = unquote(content_disposition).split('filename=')[-1].strip("\"'")
        if not filename:
            filename = unquote(urlparse(file_path).path.split('/')[-1])
        file_path = save_download_file(r.content, 'downloads', filename)
        return file_path, filename
    elif not os.path.isfile(file_path):
        raise ValueError('File path %s is not a valid file or url' % file_path)
    file_name = os.path.basename(file_path)
    # 使用 get_file_name 函数统一处理文件名
    file_name = get_file_name(file_path)
    return file_path, file_name


def get_file_name(file_path: str):
    file_name = os.path.basename(file_path)
    # 处理下是否包含了md5的逻辑
    # 更精确地处理文件名，移除前缀（格式为 tmpXXXXXX_文件名）
    if '_' in file_name:
        # 对于 tmp 开头的文件名，移除第一个下划线前的部分
        if file_name.startswith('tmp'):
            parts = file_name.split('_', 1)
            if len(parts) > 1:
                file_name = parts[1]
                # 如果还有下划线且不是URL等特殊前缀，继续移除
                if '_' in file_name and not file_name.startswith(('http', 'www')):
                    sub_parts = file_name.split('_', 1)
                    if len(sub_parts) > 1 and len(sub_parts[0]) <= 20:
                        file_name = sub_parts[1]
        else:
            # 对于其他包含下划线的文件名，只移除第一个下划线前的部分（如果是明显是哈希的前缀）
            parts = file_name.split('_', 1)
            if len(parts) > 1:
                prefix = parts[0]
                # 检查是否是哈希前缀格式 (纯字母数字字符 + 下划线，且看起来像哈希)
                # 我们通过检查前缀是否包含 both letters and digits 来判断是否像哈希
                if (prefix.isalnum() and
                    len(prefix) >= 6 and  # 哈希通常至少6个字符
                    any(c.isdigit() for c in prefix) and  # 包含数字
                    any(c.isalpha() for c in prefix)):    # 包含字母
                    file_name = parts[1]
    return file_name


def _is_valid_url(url: str):
    """Check if the url is valid."""
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)


def detect_file_type(file_path: str) -> str:
    """Detect file type based on file extension."""
    file_extension = os.path.splitext(file_path)[1].lower()
    if file_extension in ['.pdf']:
        return 'pdf'
    elif file_extension in ['.txt']:
        return 'txt'
    elif file_extension in ['.md']:
        return 'md'
    else:
        # Default to pdf if extension is not recognized
        return 'pdf'
