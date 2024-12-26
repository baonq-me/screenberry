import os
import sys


def get_env(env_name):
    if not os.getenv(env_name):
        sys.exit("Missing env $%s" % env_name)
    return os.getenv(env_name)


def remove_vietnamese_diacritics(text):
    """
    Converts a string to a slug by:
    - Removing accents and replacing special characters.
    - Converting to lowercase.
    - Replacing spaces and non-alphanumeric characters with '-'.
    - Removing extra dashes.

    Args:
        text (str): The input string.

    Returns:
        str: The unified version of the string.
    """
    # Define the mapping for removing accents
    from_chars = "àáãảạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệđùúủũụưừứửữựòóỏõọôồốổỗộơờớởỡợìíỉĩịäëïîöüûñçýỳỹỵỷ"
    to_chars = "aaaaaaaaaaaaaaaaaeeeeeeeeeeeduuuuuuuuuuuoooooooooooooooooiiiiiaeiiouuncyyyyy"
    translation_table = str.maketrans(from_chars, to_chars)

    # Remove accents
    return text.translate(translation_table)