
# SPDX-License-Identifier: MIT

# This script is intended to unpack "pkg" file from Trails of Cold Steel I/II/III/IV Vita/PS3/PS4/Switch, Trails into Reverie, and Tokyo Xanadu.
# Run the script with "--help" as the argument for descriptions of the options.

# For Trails into Reverie CLE PC and Trails of Cold Steel III/IV/Trails into Reverie NISA Switch support, it requires the "zstandard" module to be installed.
# This can be installed by:
# /path/to/python3 -m pip install zstandard

import io
import sys
import struct

try:
    import zstandard
except:
    pass

def uncompress_nislzss(src, decompressed_size, compressed_size):
    des = int.from_bytes(src.read(4), byteorder="little")
    if des != decompressed_size:
        des = des if (des > decompressed_size) else decompressed_size
    cms = int.from_bytes(src.read(4), byteorder="little")
    if (cms != compressed_size) and ((compressed_size - cms) != 4) and not (decompressed_size == 451019 and compressed_size == 176128 and cms == 176796):
        raise Exception("compression size in header and stream don't match")
    num3 = int.from_bytes(src.read(4), byteorder="little")
    fin = src.tell() + cms - 13
    cd = bytearray(des)
    num4 = 0

    while src.tell() <= fin:
        b = src.read(1)[0]
        if b == num3:
            b2 = src.read(1)[0]
            if b2 != num3:
                if b2 >= num3:
                    b2 -= 1
                b3 = src.read(1)[0]
                if b2 < b3:
                    for _ in range(b3):
                        cd[num4] = cd[num4 - b2]
                        num4 += 1
                else:
                    sliding_window_pos = num4 - b2
                    cd[num4:num4 + b3] = cd[sliding_window_pos:sliding_window_pos + b3]
                    num4 += b3
            else:
                cd[num4] = b2
                num4 += 1
        else:
            cd[num4] = b
            num4 += 1

    return cd

# adapted from https://github.com/SE2Dev/PyCoD/blob/master/_lz4.py
def uncompress_lz4(src, decompressed_size, compressed_size):
    dst = bytearray(decompressed_size)
    min_match_len = 4
    num4 = 0
    fin = src.tell() + compressed_size

    def get_length(src, length):
        """get the length of a lz4 variable length integer."""
        if length != 0x0f:
            return length

        while True:
            read_buf = src.read(1)
            if len(read_buf) != 1:
                raise Exception("EOF at length read")
            len_part = read_buf[0]

            length += len_part

            if len_part != 0xff:
                break

        return length

    while src.tell() <= fin:
        # decode a block
        read_buf = src.read(1)
        if not read_buf:
            raise Exception("EOF at reading literal-len")
        token = read_buf[0]

        literal_len = get_length(src, (token >> 4) & 0x0f)

        # copy the literal to the output buffer
        read_buf = src.read(literal_len)

        if len(read_buf) != literal_len:
            raise Exception("not literal data")
        dst[num4:num4 + literal_len] = read_buf[:literal_len]
        num4 += literal_len
        read_buf = src.read(2)
        if not read_buf or src.tell() > fin:
            if token & 0x0f != 0:
                raise Exception("EOF, but match-len > 0: %u" % (token % 0x0f, ))
            break

        if len(read_buf) != 2:
            raise Exception("premature EOF")

        offset = read_buf[0] | (read_buf[1] << 8)

        if offset == 0:
            raise Exception("offset can't be 0")

        match_len = get_length(src, (token >> 0) & 0x0f)
        match_len += min_match_len

        # append the sliding window of the previous literals
        if offset < match_len:
            for _ in range(match_len):
                dst[num4] = dst[num4-offset]
                num4 += 1
        else:
            sliding_window_pos = num4 - offset
            dst[num4:num4 + match_len] = dst[sliding_window_pos:sliding_window_pos + match_len]
            num4 += match_len

    return dst

def uncompress_zstd(src, decompressed_size, compressed_size):
    dctx = zstandard.ZstdDecompressor()
    uncompressed = dctx.decompress(src.read(compressed_size), max_output_size=decompressed_size)
    return uncompressed

def unpack_pkg(srcpath, open_r_callback, open_w_callback, filter_entry_callback=None, srccommonpkgpath=None):
    with open_r_callback(srcpath) as f:
        # Skip first four bytes
        f.seek(4, io.SEEK_CUR)
        package_file_entries = {}
        total_file_entries, = struct.unpack("<I", f.read(4))
        for i in range(total_file_entries):
            file_entry_name, file_entry_uncompressed_size, file_entry_compressed_size, file_entry_offset, file_entry_flags = struct.unpack("<64sIIII", f.read(64+4+4+4+4))
            package_file_entries[file_entry_name.rstrip(b"\x00")] = [file_entry_offset, file_entry_compressed_size, file_entry_uncompressed_size, file_entry_flags]
        common_pkg_file_entries = []
        for file_entry_name in sorted(package_file_entries.keys()):
            file_entry = package_file_entries[file_entry_name]
            if ((file_entry[3] & 1) != 0) and ((file_entry[3] & 8) != 0) and (file_entry[0] == 0) and (file_entry[1] == 0):
                common_pkg_file_entries.append(file_entry_name)
        if len(common_pkg_file_entries) > 0 and srccommonpkgpath != None:
            def filter_cb(fn, fe):
                if fn in common_pkg_file_entries:
                    return False
                return True
            unpack_pkg(srcpath=srccommonpkgpath, open_r_callback=open_r_callback, open_w_callback=open_w_callback, filter_entry_callback=filter_cb)
        for file_entry_name in sorted(package_file_entries.keys()):
            file_entry = package_file_entries[file_entry_name]
            if filter_entry_callback != None:
                if filter_entry_callback(file_entry_name, file_entry):
                    continue
            if ((file_entry[3] & 1) != 0) and ((file_entry[3] & 8) != 0) and (file_entry[0] == 0) and (file_entry[1] == 0):
                if srccommonpkgpath == None:
                    print(("File %s references common.pkg, but it was not found") % (file_entry_name.decode("ASCII")))
                continue
            f.seek(file_entry[0])
            output_data = None
            if file_entry[3] & 2:
                # This is the crc32 of the file, but we don't handle this yet
                f.seek(4, io.SEEK_CUR)
            if file_entry[3] & 4:
                output_data = uncompress_lz4(f, file_entry[2], file_entry[1])
            elif (file_entry[3] & 8) or (file_entry[3] & 16): # 8 is used for CLE PC, 16 is used for NISA Switch (works also on NISA PC version)
                if "zstandard" in sys.modules:
                    output_data = uncompress_zstd(f, file_entry[2], file_entry[1])
                else:
                    print(("File %s could not be extracted because zstandard module is not installed") % (file_entry_name.decode("ASCII")))
            elif file_entry[3] & 1:
                # This flag is both used by nislzss and lz4. Probe to differentiate between them
                is_lz4 = True
                decompressed_size = file_entry[2]
                compressed_size = file_entry[1]
                if compressed_size >= 8:
                    f.seek(4, io.SEEK_CUR) # decompressed size
                    cms = int.from_bytes(f.read(4), byteorder="little")
                    f.seek(-8, io.SEEK_CUR)
                    is_lz4 = (cms != compressed_size) and ((compressed_size - cms) != 4) and not (decompressed_size == 451019 and compressed_size == 176128 and cms == 176796)
                if is_lz4:
                    output_data = uncompress_lz4(f, file_entry[2], file_entry[1])
                else:
                    output_data = uncompress_nislzss(f, file_entry[2], file_entry[1])
            else:
                output_data = f.read(file_entry[2])
            if output_data is not None:
                with open_w_callback(file_entry_name.decode("ASCII")) as wf:
                    wf.write(output_data)

def standalone_main():
    import argparse
    import textwrap
    import os

    parser = argparse.ArgumentParser(
        description='Unpacks ".pkg" files from ED8 / Trails of Cold Steel series of games.',
        usage='Use "%(prog)s --help" for more information.',
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("input_file",
        type=str,
        help="The input pkg file.")
    parser.add_argument("--output-path",
        type=str,
        default="",
        help=textwrap.dedent('''\
            The path to the output directory.
            If it does not already exist, it will be created.
            If the path name is empty, it will default to the input pathname with "__" appended to it.
        ''')
        )
    parser.add_argument("--common-pkg-file",
        type=str,
        default="",
        help=textwrap.dedent('''\
            The path to common.pkg.
            If the path name is empty, it will attempt to search for a file in the same directory as input_file.
        ''')
        )
    args = parser.parse_args()

    input_file = os.path.realpath(args.input_file)
    if not os.path.isfile(input_file):
        raise Exception("Passed in path is not file")

    out_dir = args.output_path
    if out_dir == "":
        out_dir = input_file + "__"
    try:
        os.makedirs(name=out_dir)
    except FileExistsError as e:
        pass

    common_pkg_file = args.common_pkg_file
    if common_pkg_file == "":
        common_pkg_file = None
        input_file_basepath = os.path.dirname(input_file)
        common_pkg_file_test = input_file_basepath + "/common.pkg"
        if os.path.isfile(common_pkg_file_test):
            common_pkg_file = common_pkg_file_test
    else:
        if not os.path.isfile(common_pkg_file):
            raise Exception("Passed in path is not file")

    def open_r_callback(path):
        return open(path, "rb")
    def open_w_callback(path):
        return open(out_dir + "/" + path, "wb")
    unpack_pkg(srcpath=args.input_file, open_r_callback=open_r_callback, open_w_callback=open_w_callback, srccommonpkgpath=common_pkg_file)

if __name__ == "__main__":
    standalone_main()
