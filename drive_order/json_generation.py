"""Minimal LM Format Enforcer bridge using public tokenizer/generate APIs.

Its bundled Transformers bridge imports a tokenizer module removed in Transformers 5.
"""
from lmformatenforcer import JsonSchemaParser, TokenEnforcer, TokenEnforcerTokenizerData


def tokenizer_data(tokenizer):
    prefix = tokenizer.encode('0', add_special_tokens=False)[-1]
    special = set(tokenizer.all_special_ids)
    regular = []
    for token_id in range(len(tokenizer)):
        if token_id in special:
            continue
        text = tokenizer.decode([prefix, token_id])[1:]
        standalone = tokenizer.decode([token_id])
        regular.append((token_id, text, len(text) > len(standalone)))
    data = TokenEnforcerTokenizerData(regular,
        lambda ids: tokenizer.decode(ids).rstrip('\ufffd'), tokenizer.eos_token_id,
        False, len(tokenizer))
    # Byte-level tokenizers can assemble Hangul syllables absent as standalone
    # vocabulary tokens. Keep those decoded characters valid inside JSON strings.
    data.tokenizer_alphabet += ''.join(chr(c) for c in range(0xAC00, 0xD7A4))
    return data


def prefix_filter(data, schema):
    enforcer = TokenEnforcer(data, JsonSchemaParser(schema))
    return lambda batch_id, tokens: enforcer.get_allowed_tokens(tokens.tolist()).allowed_tokens
