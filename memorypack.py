"""MemoryPack 线格式读取器 + 存档的字符串编码"""

import struct


class Reader:
    """在一个 bytes 上按 MemoryPack 规则顺序读取"""

    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    # --- 基础 ---
    def eof(self):
        return self.pos >= len(self.data)

    def remaining(self):
        return len(self.data) - self.pos

    def _take(self, n):
        if self.pos + n > len(self.data):
            raise EOFError('读取越界: 需要 %d 字节, 只剩 %d' % (n, self.remaining()))
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def peek(self, n=1):
        return self.data[self.pos:self.pos + n]

    def skip(self, n):
        self._take(n)

    def u8(self):
        return self._take(1)[0]

    def i8(self):
        return struct.unpack('<b', self._take(1))[0]

    def boolean(self):
        return self.u8() != 0

    def u16(self):
        return struct.unpack('<H', self._take(2))[0]

    def i16(self):
        return struct.unpack('<h', self._take(2))[0]

    def u32(self):
        return struct.unpack('<I', self._take(4))[0]

    def i32(self):
        return struct.unpack('<i', self._take(4))[0]

    def u64(self):
        return struct.unpack('<Q', self._take(8))[0]

    def i64(self):
        return struct.unpack('<q', self._take(8))[0]

    def f32(self):
        return struct.unpack('<f', self._take(4))[0]

    def f64(self):
        return struct.unpack('<d', self._take(8))[0]

    def varint(self):
        """MemoryPack 的变长整数"""
        shift = 0
        value = 0
        while True:
            b = self.u8()
            value |= (b & 0x7F) << shift
            if not (b & 0x80):
                return value
            shift += 7

    # --- 组合类型 ---
    def object_header(self):
        """引用类型的对象头，返回成员数"""
        count = self.u8()
        if count < 250:
            return count
        if count == 250:
            b2 = self.u8()
            return self.varint() if b2 == 255 else b2
        return 0

    def collection_header(self):
        """集合长度，返回 None 表示 null"""
        n = self.i32()
        return None if n < 0 else n

    def string(self):
        """字符串i32 -(字符数+1) + i32 字节长度 + UTF-8"""
        neg = self.i32()
        if neg == -1:
            return None
        n = self.i32()
        if n < 0:
            return None
        return self._take(n).decode('utf-8', 'replace')


def string_at(data, off):
    """尝试把 off 当成一个字符串的起点读出来，失败返回 None

    校验条件 `neg == -(byteLen + 1)`
    """
    if off + 8 > len(data):
        return None
    neg, n = struct.unpack_from('<ii', data, off)
    if n <= 0 or n > 256 or off + 8 + n > len(data):
        return None
    if neg != -(n + 1):
        return None
    raw = data[off + 8:off + 8 + n]
    if not all(32 <= c < 127 for c in raw):
        return None
    return raw.decode('ascii')


def scan_strings(data, max_len=256):
    """扫描全文件的字符串，返回 [(偏移, 文本)]"""
    out = []
    i = 0
    n = len(data)
    while i + 8 <= n:
        s = string_at(data, i)
        if s is not None:
            out.append((i, s))
            i += 8 + len(s)
            continue
        i += 1
    return out
