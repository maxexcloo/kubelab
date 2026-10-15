"""Display HEISS tool images without sending generated media back for analysis."""
import ast
import hashlib
import inspect
from pathlib import Path
import re

EXPECTED = 'a4139811ba7e75b12dc4590be69623332293a3eb724bb8b536718887d23ee52e'


def media_display_output(output):
    if not isinstance(output, list):
        return output
    media_calls = {
        item.get('call_id') for item in output
        if item.get('type') == 'function_call' and item.get('name', '').startswith('bento_media_')
    }
    return [
        {**item, 'output': [part for part in item.get('output', []) if part.get('type') != 'input_image']}
        if item.get('type') == 'function_call_output' and item.get('call_id') in media_calls else item
        for item in output
    ]


def patch(source):
    assert hashlib.sha256(source.encode()).hexdigest() == EXPECTED, 'Review the pinned Open WebUI middleware before updating this patch.'
    before = '    convert_output_to_messages,\n'
    assert source.count(before) == 1
    source = source.replace(before, '    convert_output_to_messages as original_convert_output_to_messages,\n')
    before = 'async def store_tool_result_image(request, image_url, metadata, user):'
    assert source.count(before) == 1
    helper = inspect.getsource(media_display_output) + '\n\ndef convert_output_to_messages(output, *args, **kwargs):\n    return original_convert_output_to_messages(media_display_output(output), *args, **kwargs)\n\n\n'
    source = source.replace(before, helper + before)
    # Persist each native MCP image as a frontend file, including both tool-execution paths.
    pattern = r"(?m)^( +)output_parts.append\(\{'type': 'input_image', 'image_url': image_url\}\)$"
    source, count = re.subn(pattern, r"\1display_files.append({**file_item, 'url': image_url})\n\1output_parts.append({'type': 'input_image', 'image_url': image_url})", source)
    assert count == 2, 'Review both Open WebUI tool image delivery paths.'
    ast.parse(source)
    return source


if __name__ == '__main__':
    import sys
    source = Path('/app/backend/open_webui/utils/middleware.py') if len(sys.argv) < 2 else Path(sys.argv[1])
    target = Path('/patched/middleware.py') if len(sys.argv) < 3 else Path(sys.argv[2])
    target.write_text(patch(source.read_text()))
