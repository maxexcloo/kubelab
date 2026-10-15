"""HEISS-generated previews belong in chat rather than model vision input."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('tool_images', ROOT / 'apps/base/open-webui/tool-images.py')
images = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(images)


class ToolImageTests(unittest.TestCase):
    def test_media_images_are_display_only_and_other_tools_and_user_images_are_preserved(self):
        parts = [{'type': 'input_text', 'text': 'Done'}, {'type': 'input_image', 'image_url': 'fixture'}]
        output = [
            {'type': 'function_call', 'name': 'bento_media_nsfw_heiss_x-get_result', 'call_id': 'media'},
            {'type': 'function_call_output', 'call_id': 'media', 'output': parts, 'files': [{'type': 'image', 'url': 'fixture'}]},
            {'type': 'function_call', 'name': 'other_tool', 'call_id': 'other'},
            {'type': 'function_call_output', 'call_id': 'other', 'output': parts},
            {'type': 'message', 'content': [{'type': 'input_image', 'image_url': 'user-fixture'}]},
        ]
        result = images.media_display_output(output)
        self.assertEqual(result[1]['output'], parts[:1])
        self.assertEqual(result[1]['files'], output[1]['files'])
        self.assertEqual(result[3:], output[3:])
        self.assertEqual(output[1]['output'], parts)

    def test_changed_upstream_source_requires_patch_review(self):
        with self.assertRaises(AssertionError):
            images.patch('changed upstream source')
