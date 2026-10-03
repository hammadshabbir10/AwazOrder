"""Numbers as Urdu words, for text that will be read aloud.

Text-to-speech voices misread figures like "43,300" or "Rs 7,700" in Urdu
text (commas, currency symbols, mixed scripts), so spoken replies spell every
number out: 43300 -> "تینتالیس ہزار تین سو".
"""

# Urdu numbers 0-99 are irregular, so each has its own word.
_UNITS = (
    "صفر ایک دو تین چار پانچ چھ سات آٹھ نو دس گیارہ بارہ تیرہ چودہ پندرہ سولہ سترہ اٹھارہ انیس "
    "بیس اکیس بائیس تئیس چوبیس پچیس چھبیس ستائیس اٹھائیس انتیس "
    "تیس اکتیس بتیس تینتیس چونتیس پینتیس چھتیس سینتیس اڑتیس انتالیس "
    "چالیس اکتالیس بیالیس تینتالیس چوالیس پینتالیس چھیالیس سینتالیس اڑتالیس انچاس "
    "پچاس اکاون باون ترپن چون پچپن چھپن ستاون اٹھاون انسٹھ "
    "ساٹھ اکسٹھ باسٹھ تریسٹھ چونسٹھ پینسٹھ چھیاسٹھ سڑسٹھ اڑسٹھ انہتر "
    "ستر اکہتر بہتر تہتر چوہتر پچہتر چھہتر ستتر اٹھہتر اناسی "
    "اسی اکیاسی بیاسی تراسی چوراسی پچاسی چھیاسی ستاسی اٹھاسی نواسی "
    "نوے اکانوے بانوے ترانوے چورانوے پچانوے چھیانوے ستانوے اٹھانوے ننانوے"
).split()

assert len(_UNITS) == 100

# South Asian grouping: crore (10^7), lakh (10^5), thousand, hundred.
_SCALES = ((10_000_000, "کروڑ"), (100_000, "لاکھ"), (1_000, "ہزار"), (100, "سو"))


def integer_words(n: int) -> str:
    if n < 0:
        return "منفی " + integer_words(-n)
    if n < 100:
        return _UNITS[n]
    parts = []
    for size, word in _SCALES:
        if n >= size:
            parts.append(f"{integer_words(n // size)} {word}")
            n %= size
    if n:
        parts.append(_UNITS[n])
    return " ".join(parts)


def quantity_words(q: float) -> str:
    """Quantities step by halves: 0.5 آدھا, 1.5 ڈیڑھ, 2.5 ڈھائی, 3.5 ساڑھے تین."""
    whole, frac = int(q), round(q - int(q), 2)
    if frac == 0:
        return integer_words(whole)
    if frac == 0.5:
        if whole == 0:
            return "آدھا"
        if whole == 1:
            return "ڈیڑھ"
        if whole == 2:
            return "ڈھائی"
        return f"ساڑھے {integer_words(whole)}"
    return f"{integer_words(whole)} اعشاریہ {integer_words(int(round(frac * 100)))}"


def rupees_words(amount: float) -> str:
    return f"{integer_words(round(amount))} روپے"
