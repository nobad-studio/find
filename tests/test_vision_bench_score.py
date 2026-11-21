"""tools/vision_bench/score.py: answers scored the same way on every PC and model (dev-only benchmark)."""
from tools.vision_bench.score import aggregate, normalize, score_item


def test_normalize_hindi_and_case():
    assert normalize("  नमस्ते  World ") == normalize("नमस्ते world")


def test_text_item_is_substring_after_normalize():
    assert score_item({"kind": "text", "expect": "EXIT 12"}, "The sign says: exit  12.") == 1.0
    assert score_item({"kind": "text", "expect": "EXIT 12"}, "No text") == 0.0


def test_hindi_text_item():
    assert score_item({"kind": "text", "expect": "बाहर निकलें"}, "बोर्ड पर लिखा है: बाहर  निकलें।") == 1.0


def test_objects_item_is_fraction_of_expected_found():
    item = {"kind": "objects", "expect": ["dog", "car"]}
    assert score_item(item, "a dog next to a bicycle") == 0.5


def test_objects_synonyms():
    item = {"kind": "objects", "expect": [["car", "vehicle"]]}
    assert score_item(item, "a red vehicle") == 1.0


def test_objects_whole_words_only():
    assert score_item({"kind": "objects", "expect": ["cat"]}, "a catalogue") == 0.0


def test_count_item_reads_first_number_or_word():
    assert score_item({"kind": "count", "expect": 2}, "There are two boys.") == 1.0
    assert score_item({"kind": "count", "expect": 2}, "3 boys") == 0.0


def test_yesno_item():
    assert score_item({"kind": "yesno", "expect": True}, "Yes, same place.") == 1.0
    assert score_item({"kind": "yesno", "expect": True}, "No.") == 0.0
    assert score_item({"kind": "yesno", "expect": False}, "I can't tell") == 0.0


def test_describe_item_is_keyword_hit_rate():
    item = {"kind": "describe", "expect": ["beach", "sunset", "two people"]}
    assert abs(score_item(item, "Two people on a beach.") - 2 / 3) < 1e-9


def test_aggregate():
    assert aggregate([("text", 1.0), ("text", 0.0), ("count", 1.0)]) == {"text": 0.5, "count": 1.0, "all": 2 / 3}


def test_aggregate_empty():
    assert aggregate([]) == {"all": 0.0}
