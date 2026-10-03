"""``search_key(text)`` (ADR-060 item 8): one spelling in English letters for a name or a typed
search, written in English letters or in Devanagari, so that "चावल", "chawal" and "chaaval" meet
("caval"), as do "टाटा" and "Tata" ("tata"), "नमकीन" and "namkeen" ("namkin"). Indexes use it and so
does the typed text, so both sides always agree. A key is only for matching; nobody sees it.

How (each step applies to both scripts unless it says otherwise):
1. English letters: one letter per sound: c (not ch) as k, ch/chh as c, ph as f, sh as s, x as ks,
   aspirates without their h (kh, gh, jh, th, dh, bh, rh), q as k, w as v, z as j.
2. Devanagari to the same letters, aspirates and their plain letters alike; ज्ञ as gy. A
   consonant's own vowel is written where another letter follows it in the word (none at the end
   of a word: नमक → namak), and dropped where Hindi drops it, between a vowel and a consonant
   followed by a vowel, from the end of the word backwards: नमकीन → namkin, not namakin;
   अगरबत्ती → agarbatti.
3. Long vowels and doubled letters as one (aa → a, ee → i, oo → u, tt → t); ai as a (मैगी, Maggi);
   m before p, b or f as n (अंबुजा, ambuja).

More scripts later (Gujarati, Kannada, …) add their letters to step 2."""

from django.db import migrations

# Step 2: each Devanagari letter, vowel sign or digit and its English letter.
DEVANAGARI = {
    "क": "k", "ख": "k", "ग": "g", "घ": "g", "ङ": "n",
    "च": "c", "छ": "c", "ज": "j", "झ": "j", "ञ": "n",
    "ट": "t", "ठ": "t", "ड": "d", "ढ": "d", "ण": "n",
    "त": "t", "थ": "t", "द": "d", "ध": "d", "न": "n", "ऩ": "n",
    "प": "p", "फ": "f", "ब": "b", "भ": "b", "म": "m",
    "य": "y", "र": "r", "ऱ": "r", "ल": "l", "ळ": "l", "ऴ": "l", "व": "v",
    "श": "s", "ष": "s", "स": "s", "ह": "h",
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ए": "e", "ऎ": "e", "ऍ": "e", "ओ": "o", "ऒ": "o", "ऑ": "o",
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
    "े": "e", "ॆ": "e", "ॅ": "e", "ो": "o", "ॊ": "o", "ॉ": "o",
    "ं": "n", "ँ": "n", "ः": "h",
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
    "।": " ", "॥": " ",
}  # fmt: skip
DROPPED = "़्ऽ"  # nukta (ड़ is read as ड), virama, avagraha
FROM = "".join(DEVANAGARI) + DROPPED
TO = "".join(DEVANAGARI.values())
assert all(len(letter) == 1 for letter in DEVANAGARI.values())

CONSONANT = "[b-df-hj-np-tv-z]"

SQL = rf"""
CREATE FUNCTION search_key(raw text) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $fn$
DECLARE
  s text := normalize(lower(raw), NFC);
BEGIN
  -- 1. English letters: one letter per sound.
  s := regexp_replace(s, 'c(?!h)', 'k', 'g');
  s := regexp_replace(s, 'chh?', 'c', 'g');
  s := replace(replace(replace(s, 'ph', 'f'), 'sh', 's'), 'x', 'ks');
  s := regexp_replace(s, '([kgjtdbr])h', '\1', 'g');
  s := translate(s, 'qwz', 'kvj');
  -- 2. Devanagari. A consonant's own vowel (ə) wherever a letter follows it in the word.
  s := replace(s, 'ज्ञ', 'ग्य');
  s := regexp_replace(s, '([क-ह]़?)(?=[क-हअ-औंँः])', '\1ə', 'g');
  s := replace(replace(replace(s, 'ै', 'ai'), 'ऐ', 'ai'), 'ौ', 'au');
  s := replace(replace(replace(s, 'औ', 'au'), 'ृ', 'ri'), 'ऋ', 'ri');
  s := translate(s, '{FROM}', '{TO}');
  -- ... dropped between a vowel and a consonant followed by a vowel, from the end backwards
  -- (the pattern reads the same both ways, so it runs on the reversed text).
  s := reverse(regexp_replace(
    reverse(s), '([aeiouə]{CONSONANT})ə(?={CONSONANT}[aeiouə])', '\1', 'g'));
  s := replace(s, 'ə', 'a');
  -- 3. Long vowels and doubled letters as one.
  s := replace(replace(replace(s, 'ee', 'i'), 'oo', 'u'), 'ai', 'a');
  s := regexp_replace(s, 'm(?=[pbf])', 'n', 'g');
  RETURN regexp_replace(s, '([a-z])\1+', '\1', 'g');
END
$fn$;
"""


class Migration(migrations.Migration):
    dependencies = [("common", "0001_initial")]

    operations = [
        migrations.RunSQL(SQL, "DROP FUNCTION IF EXISTS search_key(text);"),
    ]
