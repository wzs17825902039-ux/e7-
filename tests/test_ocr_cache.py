from pathlib import Path
import tempfile
import unittest
import numpy as np

from e7_assistant.local_ocr import CachedOCREngine


class OCRCacheTests(unittest.TestCase):
    def engine(self, image, **kwargs):
        self.calls += 1
        return [[['85', .99]], [1.0]]

    def setUp(self):
        self.calls = 0

    def test_exact_pixels_and_options_only_and_result_isolation(self):
        cached = CachedOCREngine(self.engine)
        pixels = np.zeros((8, 12, 3), dtype=np.uint8)
        result = cached(pixels, use_det=False)
        result[0][0][0] = 'modified'
        self.assertEqual(cached(pixels.copy(), use_det=False)[0][0][0], '85')
        self.assertEqual(self.calls, 1)
        pixels[0, 0, 0] = 1
        cached(pixels, use_det=False)
        cached(pixels, use_det=True)
        cached(pixels.reshape(12, 8, 3), use_det=True)
        self.assertEqual(self.calls, 4)

    def test_file_content_changes_and_different_files_with_same_content(self):
        cached = CachedOCREngine(self.engine)
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory)/'a.png', Path(directory)/'b.png'
            first.write_bytes(b'original')
            second.write_bytes(b'original')
            cached(str(first), use_cls=False)
            cached(str(second), use_cls=False)
            self.assertEqual(self.calls, 1)
            first.write_bytes(b'changed!')
            cached(str(first), use_cls=False)
            self.assertEqual(self.calls, 2)

    def test_lru_and_byte_limits_and_failures(self):
        cached = CachedOCREngine(self.engine, max_entries=1, max_bytes=12)
        a = np.zeros((1, 2, 3), dtype=np.uint8)
        b = a + 1
        cached(a); cached(b); cached(a)
        self.assertEqual(self.calls, 3)
        cached(np.zeros((10, 10, 3), dtype=np.uint8))
        self.assertLessEqual(cached.bytes, 12)
        self.assertEqual(len(cached.cache), 1)
        def failed(image, **kwargs):
            raise RuntimeError('failed')
        broken = CachedOCREngine(failed)
        for _ in range(2):
            with self.assertRaises(RuntimeError):broken(a)
        self.assertFalse(broken.cache)


if __name__ == '__main__': unittest.main()
