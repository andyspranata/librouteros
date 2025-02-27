# -*- coding: UTF-8 -*-

from struct import pack, unpack
from logging import getLogger, NullHandler

from librouteros.exceptions import ConnectionError, FatalError

LOGGER = getLogger('librouteros')
LOGGER.addHandler(NullHandler())


class Encoder:

    def encodeSentence(self, *words):
        """
        Encode given sentence in API format.

        :param words: Words to endoce.
        :returns: Encoded sentence.
        """
        encoded = map(self.encodeWord, words)
        encoded = b''.join(encoded)
        # append EOS (end of sentence) byte
        encoded += b'\x00'
        return encoded

    def encodeWord(self, word):
        """
        Encode word in API format.

        :param word: Word to encode.
        :returns: Encoded word.
        """
        encoded_word = word.encode(encoding=self.encoding, errors='strict')
        return Encoder.encodeLength(len(word)) + encoded_word

    @staticmethod
    def encodeLength(length):
        """
        Encode given length in mikrotik format.

        :param length: Integer < 268435456.
        :returns: Encoded length.
        """
        if length < 128:
            ored_length = length
            offset = -1
        elif length < 16384:
            ored_length = length | 0x8000
            offset = -2
        elif length < 2097152:
            ored_length = length | 0xC00000
            offset = -3
        elif length < 268435456:
            ored_length = length | 0xE0000000
            offset = -4
        else:
            raise ConnectionError('Unable to encode length of {}'.format(length))

        return pack('!I', ored_length)[offset:]


class Decoder:

    @staticmethod
    def determineLength(length):
        """
        Given first read byte, determine how many more bytes
        needs to be known in order to get fully encoded length.

        :param length: First read byte.
        :return: How many bytes to read.
        """
        integer = ord(length)

        if integer < 128:
            return 0
        elif integer < 192:
            return 1
        elif integer < 224:
            return 2
        elif integer < 240:
            return 3
        else:
            raise ConnectionError('Unknown controll byte {}'.format(length))

    @staticmethod
    def decodeLength(length):
        """
        Decode length based on given bytes.

        :param length: Bytes string to decode.
        :return: Decoded length.
        """
        bytes_length = len(length)

        if bytes_length < 2:
            offset = b'\x00\x00\x00'
            XOR = 0
        elif bytes_length < 3:
            offset = b'\x00\x00'
            XOR = 0x8000
        elif bytes_length < 4:
            offset = b'\x00'
            XOR = 0xC00000
        elif bytes_length < 5:
            offset = b''
            XOR = 0xE0000000
        else:
            raise ConnectionError('Unable to decode length of {}'.format(length))

        decoded = unpack('!I', (offset + length))[0]
        decoded ^= XOR
        return decoded


class ApiProtocol(Encoder, Decoder):

    def __init__(self, transport, encoding):
        self.transport = transport
        self.encoding = encoding

    def log(self, direction_string, *sentence):
        for word in sentence:
            LOGGER.debug('{0} {1!r}'.format(direction_string, word))

        LOGGER.debug('{0} EOS'.format(direction_string))

    def writeSentence(self, cmd, *words):
        """
        Write encoded sentence.

        :param cmd: Command word.
        :param words: Aditional words.
        """
        encoded = self.encodeSentence(cmd, *words)
        self.log('<---', cmd, *words)
        self.transport.write(encoded)

    def readSentence(self):
        """
        Read every word untill empty word (NULL byte) is received.

        :return: Reply word, tuple with read words.
        """
        sentence = tuple(word for word in iter(self.readWord, b''))
        self.log('--->', *sentence)
        reply_word, words = sentence[0], sentence[1:]
        if reply_word == '!fatal':
            self.transport.close()
            raise FatalError(words[0])
        else:
            return reply_word, words

    def readWord(self):
        byte = self.transport.read(1)
        to_read = self.determineLength(byte)
        byte += self.transport.read(to_read)
        length = self.decodeLength(byte)
        return self.transport.read(length).decode(encoding=self.encoding, errors='strict')

    def close(self):
        self.transport.close()


class SocketTransport:

    def __init__(self, sock):
        self.sock = sock

    def write(self, data):
        """
        Write given bytes to socket. Loop as long as every byte in
        string is written unless exception is raised.
        """
        self.sock.sendall(data)

    def read(self, length):
        """
        Read as many bytes from socket as specified in length.
        Loop as long as every byte is read unless exception is raised.
        """
        data = bytearray()
        while len(data) != length:
            data += self.sock.recv((length - len(data)))
            if not data:
                raise ConnectionError('Connection unexpectedly closed.')
        return data

    def close(self):
        self.sock.close()
