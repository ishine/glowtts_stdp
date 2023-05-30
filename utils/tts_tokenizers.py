# -*- coding: utf-8 -*-
# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools
import string
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import List, Optional

from nemo_text_processing.g2p.data.data_utils import english_text_preprocessing

from nemo.utils import logging


class BaseTokenizer(ABC):
    PAD, BLANK, OOV = '<pad>', '<blank>', '<oov>'

    def __init__(self, tokens, *, pad=PAD, blank=BLANK, oov=OOV, sep='', add_blank_at=None, ):
        """Abstract class for creating an arbitrary tokenizer to convert string to list of int tokens.
        Args:
            tokens: List of tokens.
            pad: Pad token as string.
            blank: Blank token as string.
            oov: OOV token as string.
            sep: Separation token as string.
            add_blank_at: Add blank to labels in the specified order ("last") or after tokens (any non None),
             if None then no blank in labels.
        """
        super().__init__()

        tokens = list(tokens)
        self.pad, tokens = len(tokens), tokens + [pad]  # Padding

        if add_blank_at is not None:
            self.blank, tokens = len(tokens), tokens + [blank]  # Reserved for blank from asr-model
        else:
            # use add_blank_at=None only for ASR where blank is added automatically, disable blank here
            self.blank = None

        self.oov, tokens = len(tokens), tokens + [oov]  # Out Of Vocabulary

        if add_blank_at == "last":
            tokens[-1], tokens[-2] = tokens[-2], tokens[-1]
            self.oov, self.blank = self.blank, self.oov

        self.tokens = tokens
        self.sep = sep

        self._util_ids = {self.pad, self.blank, self.oov}
        self._token2id = {l: i for i, l in enumerate(tokens)}
        self._id2token = tokens

    def __call__(self, text: str) -> List[int]:
        return self.encode(text)

    @abstractmethod
    def encode(self, text: str) -> List[int]:
        """Turns str text into int tokens."""
        pass

    def decode(self, tokens: List[int]) -> str:
        """Turns ints tokens into str text."""
        return self.sep.join(self._id2token[t] for t in tokens if t not in self._util_ids)

    def intersperse(self, token, item):
        result = [item] * (len(token) * 2 + 1)
        result[1::2] = token
        return result


class BaseCharsTokenizer(BaseTokenizer):
    # fmt: off
    PUNCT_LIST = (  # Derived from LJSpeech and "/" additionally
        ',', '.', '!', '?', '-',
        ':', ';', '/', '"', '(',
        ')', '[', ']', '{', '}',
    )
    # fmt: on

    def __init__(
        self,
        chars,
        punct=True,
        apostrophe=True,
        add_blank_at=None,
        pad_with_space=False,
        non_default_punct_list=None,
        text_preprocessing_func=lambda x: x,
        add_blank_to_text=False,
    ):
        """Base class for char-based tokenizer.
        Args:
            chars: string that represents all possible characters.
            punct: Whether to reserve grapheme for basic punctuation or not.
            apostrophe: Whether to use apostrophe or not.
            add_blank_at: Add blank to labels in the specified order ("last") or after tokens (any non None),
             if None then no blank in labels.
            pad_with_space: Whether to pad text with spaces at the beginning and at the end or not.
            non_default_punct_list: List of punctuation marks which will be used instead default.
            text_preprocessing_func: Text preprocessing function for correct execution of the tokenizer.
        """

        tokens = []
        self.space, tokens = len(tokens), tokens + [' ']  # Space
        tokens.extend(chars)
        if apostrophe:
            tokens.append("'")  # Apostrophe for saving "don't" and "Joe's"

        if punct:
            if non_default_punct_list is not None:
                self.PUNCT_LIST = non_default_punct_list
            tokens.extend(self.PUNCT_LIST)

        add_blank_at = "last" if add_blank_to_text else add_blank_at
        self.add_blank_to_text = add_blank_to_text
        
        super().__init__(tokens, add_blank_at=add_blank_at)

        self.punct = punct
        self.pad_with_space = pad_with_space

        self.text_preprocessing_func = text_preprocessing_func

    def encode(self, text):
        """See base class."""
        cs, space, tokens = [], self.tokens[self.space], set(self.tokens)

        text = self.text_preprocessing_func(text)
        for c in text:
            # Add space if last one isn't one
            if c == space and len(cs) > 0 and cs[-1] != space:
                cs.append(c)
            # Add next char
            elif (c.isalnum() or c == "'") and c in tokens:
                cs.append(c)
            # Add punct
            elif (c in self.PUNCT_LIST) and self.punct:
                cs.append(c)
            # Warn about unknown char
            elif c != space:
                logging.warning(f"Text: [{text}] contains unknown char: [{c}]. Symbol will be skipped.")

        # Remove trailing spaces
        if cs:
            while cs[-1] == space:
                cs.pop()

        if self.add_blank_to_text:
            blank = self._id2token[self.blank]
            cs = self.intersperse(cs, blank)
        elif self.pad_with_space:
            cs = [space] + cs + [space]

        return [self._token2id[p] for p in cs]


class EnglishPhonemesTokenizer(BaseTokenizer):
    # fmt: off
    PUNCT_LIST = (  # Derived from LJSpeech and "/" additionally
        ',', '.', '!', '?', '-',
        ':', ';', '/', '"', '(',
        ')', '[', ']', '{', '}',
    )
    VOWELS = (
        'AA', 'AE', 'AH', 'AO', 'AW',
        'AY', 'EH', 'ER', 'EY', 'IH',
        'IY', 'OW', 'OY', 'UH', 'UW',
    )
    CONSONANTS = (
        'B', 'CH', 'D', 'DH', 'F', 'G',
        'HH', 'JH', 'K', 'L', 'M', 'N',
        'NG', 'P', 'R', 'S', 'SH', 'T',
        'TH', 'V', 'W', 'Y', 'Z', 'ZH',
    )
    # fmt: on

    def __init__(
        self,
        g2p,
        punct=True,
        non_default_punct_list=None,
        stresses=False,
        chars=False,
        *,
        space=' ',
        silence=None,
        apostrophe=True,
        oov=BaseTokenizer.OOV,
        sep='|',  # To be able to distinguish between 2/3 letters codes.
        add_blank_at=None,
        pad_with_space=False,
        text_preprocessing_func=lambda text: english_text_preprocessing(text, lower=False),
        add_blank_to_text=False,
    ):
        """English phoneme-based tokenizer.
        Args:
            g2p: Grapheme to phoneme module.
            punct: Whether to reserve grapheme for basic punctuation or not.
            non_default_punct_list: List of punctuation marks which will be used instead default.
            stresses: Whether to use phonemes codes with stresses (0-2) or not.
            chars: Whether to additionally use chars together with phonemes. It is useful if g2p module can return chars too.
            space: Space token as string.
            silence: Silence token as string (will be disabled if it is None).
            apostrophe: Whether to use apostrophe or not.
            oov: OOV token as string.
            sep: Separation token as string.
            add_blank_at: Add blank to labels in the specified order ("last") or after tokens (any non None),
             if None then no blank in labels.
            pad_with_space: Whether to pad text with spaces at the beginning and at the end or not.
            text_preprocessing_func: Text preprocessing function for correct execution of the tokenizer.
             Basically, it replaces all non-unicode characters with unicode ones.
             Note that lower() function shouldn't applied here, in case the text contains phonemes (it will be handled by g2p).
        """
        
        self.phoneme_probability = None
        if hasattr(g2p, "phoneme_probability"):
            self.phoneme_probability = g2p.phoneme_probability
        tokens = []
        self.space, tokens = len(tokens), tokens + [space]  # Space

        if silence is not None:
            self.silence, tokens = len(tokens), tokens + [silence]  # Silence

        tokens.extend(self.CONSONANTS)
        vowels = list(self.VOWELS)

        if stresses:
            vowels = [f'{p}{s}' for p, s in itertools.product(vowels, (0, 1, 2))]
        tokens.extend(vowels)

        if chars or self.phoneme_probability is not None:
            if not chars:
                logging.warning(
                    "phoneme_probability was not None, characters will be enabled even though "
                    "chars was set to False."
                )
            tokens.extend(string.ascii_lowercase)

        if apostrophe:
            tokens.append("'")  # Apostrophe

        if punct:
            if non_default_punct_list is not None:
                self.PUNCT_LIST = non_default_punct_list
            tokens.extend(self.PUNCT_LIST)
        
        add_blank_at = "last" if add_blank_to_text else add_blank_at
        self.add_blank_to_text = add_blank_to_text

        super().__init__(tokens, oov=oov, sep=sep, add_blank_at=add_blank_at)

        self.chars = chars if self.phoneme_probability is None else True
        self.punct = punct
        self.stresses = stresses
        self.pad_with_space = pad_with_space

        self.text_preprocessing_func = text_preprocessing_func
        self.g2p = g2p

    def encode(self, text):
        """See base class for more information."""

        text = self.text_preprocessing_func(text)
        g2p_text = self.g2p(text)  # TODO: handle infer
        return self.encode_from_g2p(g2p_text, text)

    def encode_from_g2p(self, g2p_text: List[str], raw_text: Optional[str] = None):
        """
        Encodes text that has already been run through G2P.
        Called for encoding to tokens after text preprocessing and G2P.

        Args:
            g2p_text: G2P's output, could be a mixture of phonemes and graphemes,
                e.g. "see OOV" -> ['S', 'IY1', ' ', 'O', 'O', 'V']
            raw_text: original raw input
        """
        ps, space, tokens = [], self.tokens[self.space], set(self.tokens)
        for p in g2p_text:  # noqa
            # Remove stress
            if p.isalnum() and len(p) == 3 and not self.stresses:
                p = p[:2]

            # Add space if last one isn't one
            if p == space and len(ps) > 0 and ps[-1] != space:
                ps.append(p)
            # Add next phoneme or char (if chars=True)
            elif (p.isalnum() or p == "'") and p in tokens:
                ps.append(p)
            # Add punct
            elif (p in self.PUNCT_LIST) and self.punct:
                ps.append(p)
            # Warn about unknown char/phoneme
            elif p != space:
                pass
                # message = f"Text: [{''.join(g2p_text)}] contains unknown char/phoneme: [{p}]."
                # if raw_text is not None:
                #     message += f"Original text: [{raw_text}]. Symbol will be skipped."
                # logging.warning(message)

        # Remove trailing spaces
        if ps:
            while ps[-1] == space:
                ps.pop()

        if self.add_blank_to_text:
            blank = self._id2token[self.blank]
            ps = self.intersperse(ps, blank)
        elif self.pad_with_space:
            ps = [space] + ps + [space]
        # if self.pad_with_space:
        #     ps = [space] + ps + [space]
        
        return [self._token2id[p] for p in ps]

    @contextmanager
    def set_phone_prob(self, prob):
        if hasattr(self.g2p, "phoneme_probability"):
            self.g2p.phoneme_probability = prob
        try:
            yield
        finally:
            if hasattr(self.g2p, "phoneme_probability"):
                self.g2p.phoneme_probability = self.phoneme_probability
                
