"""``search_key`` (ADR-060 item 8): a word written in Devanagari and the same word typed in English
letters, the common spellings included, get one key; Hindi's dropped vowels are dropped
("नमकीन" = "namkeen"); other text keeps its letters and digits."""

import pytest

from common.search_keys import key, keys

pytestmark = pytest.mark.django_db

SAME = [
    # Hindi and Marathi trade words and how shops type them.
    ("चावल", "chawal"),
    ("चावल", "chaaval"),
    ("नमक", "namak"),
    ("मीठ", "meeth"),
    ("मीठ", "mith"),
    ("साबुन", "sabun"),
    ("तांदूळ", "tandul"),
    ("तांदूळ", "tandool"),
    ("नमकीन", "namkeen"),
    ("हल्दी", "haldi"),
    ("मसाला", "masala"),
    ("आटा", "atta"),
    ("घी", "ghee"),
    ("दूध", "doodh"),
    ("दूध", "dudh"),
    ("चीनी", "cheeni"),
    ("शक्कर", "shakkar"),
    ("साखर", "sakhar"),
    ("गुड़", "gud"),
    ("गहू", "gahu"),
    ("चना", "chana"),
    ("पोहा", "poha"),
    ("बाजरी", "bajri"),
    ("कांदा", "kanda"),
    ("बटाटा", "batata"),
    ("लसूण", "lasun"),
    ("मिरची", "mirchi"),
    ("धणे", "dhane"),
    ("जीरा", "jeera"),
    ("अगरबत्ती", "agarbatti"),
    ("सरसों", "sarson"),
    ("मैदा", "maida"),
    ("किराणा", "kirana"),
    ("खोबरेल", "khobrel"),
    ("पकोड़ा", "pakoda"),
    # Brands and names.
    ("टाटा", "Tata"),
    ("पारले", "Parle"),
    ("डेटॉल", "Dettol"),
    ("मैगी", "Maggi"),
    ("शैम्पू", "shampoo"),
    ("कॉफ़ी", "coffee"),
    ("हॉर्लिक्स", "Horlicks"),
    ("अंबुजा", "Ambuja"),
    ("लक्ष्मी", "Laxmi"),
    ("ज्ञान", "gyan"),
    ("श्री", "Shri"),
    ("कमला", "Kamla"),
    ("गणेश किराना", "Ganesh Kirana"),
    ("सुरेश पाटील", "Suresh Patil"),
]


def test_a_devanagari_word_and_its_english_spelling_meet():
    texts = [text for pair in SAME for text in pair]
    found = keys(texts)
    differ = [
        (devanagari, typed, found[2 * n], found[2 * n + 1])
        for n, (devanagari, typed) in enumerate(SAME)
        if found[2 * n] != found[2 * n + 1]
    ]
    assert differ == []


def test_how_a_key_is_spelled():
    assert key("चावल") == "caval"
    assert key("नमकीन") == "namkin"  # the vowel Hindi drops is dropped
    assert key("नमक") == "namak"  # none written after the last letter
    assert key("अगरबत्ती") == "agarbati"  # dropped from the end backwards
    assert key("Tata Salt 1kg") == "tata salt 1kg"  # digits stay
    assert key("गेहूं १ किलो") == "gehun 1 kilo"  # Devanagari digits as 0-9
    assert key("Cola") == "kola" and key("Chocolate") == "cokolate"
    assert key("ગણેશ") == "ગણેશ"  # a script without letters here yet passes through
    assert key("") == ""
    assert keys([]) == []
