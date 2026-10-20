import unittest

from scripts.sample_backup import jsoncodec as codec


class JsonCodecTests(unittest.TestCase):
    def test_preserves_numeric_tokens_and_typed_values(self):
        text = '{"n":900719925474099312345,"d":1.2345678901234567890,"e":-1.20e+99,"b":true,"s":"1","z":null}'
        parsed = codec.loads(text)
        self.assertEqual(codec.dumps(parsed), text)
        self.assertFalse(codec.equal(codec.loads("1"), True))
        self.assertFalse(codec.equal(codec.loads("1"), "1"))
        self.assertFalse(codec.equal(codec.loads("1.0"), codec.loads("1")))
        self.assertTrue(codec.equal(codec.loads('{"b":2,"a":[1,1]}'),
                                    codec.loads('{"a":[1,1],"b":2}')))
        self.assertFalse(codec.equal(codec.loads("[1,2]"), codec.loads("[2,1]")))

    def test_rejects_duplicate_keys_and_non_json_numbers(self):
        for text in ('{"a":1,"a":2}', '{"a":{"b":1,"b":1}}', "NaN", "Infinity", "-Infinity"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                codec.loads(text)
