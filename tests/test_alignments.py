import pathlib
import shutil
import gzip

import numpy as np
import pytest
from numpy.testing import assert_array_equal

from sc2ts import alignments as sa
from sc2ts import core


@pytest.fixture
def data_cache():
    cache_path = pathlib.Path("tests/data/cache")
    if not cache_path.exists():
        cache_path.mkdir()
    return cache_path


@pytest.fixture
def alignments_fasta(data_cache):
    cache_path = data_cache / "alignments.fasta"
    if not cache_path.exists():
        with gzip.open("tests/data/alignments.fasta.gz") as src:
            with open(cache_path, "wb") as dest:
                shutil.copyfileobj(src, dest)
    return cache_path


@pytest.fixture
def alignments_store(data_cache, alignments_fasta):
    cache_path = data_cache / "alignments.db"
    if not cache_path.exists():
        with sa.AlignmentStore(cache_path, "a") as a:
            fasta = core.FastaReader(alignments_fasta)
            a.append(fasta, show_progress=False)
    return sa.AlignmentStore(cache_path)


class TestAlignmentsStore:
    def test_info(self, alignments_store):
        assert "contains" in str(alignments_store)

    def test_len(self, alignments_store):
        assert len(alignments_store) == 55

    def test_fetch_known(self, alignments_store):
        a = alignments_store["SRR11772659"]
        assert a.shape == (core.REFERENCE_SEQUENCE_LENGTH,)
        assert a[0] == "X"
        assert a[1] == "N"
        assert a[-1] == "N"

    def test_keys(self, alignments_store):
        keys = list(alignments_store.keys())
        assert len(keys) == len(alignments_store)
        assert "SRR11772659" in keys

    def test_in(self, alignments_store):
        assert "SRR11772659" in alignments_store
        assert "NOT_IN_STORE" not in alignments_store


def test_get_gene_coordinates():
    d = core.get_gene_coordinates()
    assert len(d) == 11
    assert d["S"] == (21563, 25384)


class TestEncodeAligment:
    @pytest.mark.parametrize(
        ["hap", "expected"],
        [
            ("A", [0]),
            ("C", [1]),
            ("G", [2]),
            ("T", [3]),
            ("-", [4]),
            ("N", [-1]),
            ("ACGT-N", [0, 1, 2, 3, 4, -1]),
            ("N-TGCA", [-1, 4, 3, 2, 1, 0]),
            ("ACAGTAC-N", [0, 1, 0, 2, 3, 0, 1, 4, -1]),
        ],
    )
    def test_examples(self, hap, expected):
        h = np.array(list(hap), dtype="U1")
        a = sa.encode_alignment(h)
        assert_array_equal(a, expected)
        assert_array_equal(h, sa.decode_alignment(a))

    @pytest.mark.parametrize("hap", "RYSWKMDHVN.")
    def test_iupac_uncertain_missing(self, hap):
        h = np.array(list(hap), dtype="U1")
        a = sa.encode_alignment(h)
        assert_array_equal(a, [-1])

    @pytest.mark.parametrize("hap", "XZxz")
    def test_other_missing(self, hap):
        h = np.array(list(hap), dtype="U1")
        a = sa.encode_alignment(h)
        assert_array_equal(a, [-1])

    @pytest.mark.parametrize("hap", "acgt")
    def test_lowercase_nucleotide_missing(self, hap):
        h = np.array(list(hap), dtype="U1")
        a = sa.encode_alignment(h)
        assert_array_equal(a, [-1])

    @pytest.mark.parametrize(
        "a",
        [
            [-2],
            [-3],
            [5],
            [6],
            [0, -2],
        ],
    )
    def test_examples(self, a):
        with pytest.raises(ValueError):
            sa.decode_alignment(np.array(a))

    def test_encode_real(self, alignments_store):
        h = alignments_store["SRR11772659"]
        a = sa.encode_alignment(h)
        assert a[0] == -1
        assert a[-1] == -1


class TestMasking:
    # Window size of 1 is weird because we have to have two or more
    # ambiguous characters. That means we only filter if something is
    # surrounded.
    @pytest.mark.parametrize(
        ["hap", "expected", "masked"],
        [
            ("A", "A", 0),
            ("-", "-", 0),
            ("-A-", "-N-", 1),
            ("NAN", "NNN", 1),
            ("---AAC---", "-N-AAC-N-", 2),
        ],
    )
    def test_examples_w1(self, hap, expected, masked):
        hap = np.array(list(hap), dtype="U1")
        a = sa.encode_alignment(hap)
        expected = np.array(list(expected), dtype="U1")
        m = sa.mask_alignment(a, window_size=1)
        assert len(m) == masked
        assert_array_equal(expected, sa.decode_alignment(a))

    @pytest.mark.parametrize(
        ["hap", "expected", "masked"],
        [
            ("A", "A", 0),
            ("-", "-", 0),
            ("--A--", "-NNN-", 3),
            ("---AAAA---", "NNNNAANNNN", 8),
            ("NNNAAAANNN", "NNNNAANNNN", 8),
            ("-N-AAAA-N-", "NNNNAANNNN", 8),
        ],
    )
    def test_examples_w2(self, hap, expected, masked):
        hap = np.array(list(hap), dtype="U1")
        a = sa.encode_alignment(hap)
        expected = np.array(list(expected), dtype="U1")
        m = sa.mask_alignment(a, window_size=2)
        assert len(m) == masked
        assert_array_equal(expected, sa.decode_alignment(a))

    @pytest.mark.parametrize("w", [0, -1, -2])
    def test_bad_window_size(self, w):
        a = np.zeros(2, dtype=np.int8)
        with pytest.raises(ValueError):
            sa.mask_alignment(a, window_size=w)


class TestEncodeAndMask:
    def test_known(self, alignments_store):
        a = alignments_store["SRR11772659"]
        ma = sa.encode_and_mask(a)
        assert ma.original_base_composition == {
            "T": 9566,
            "A": 8894,
            "G": 5850,
            "C": 5472,
            "N": 121,
        }
        assert ma.original_md5 == "e96feaa72c4f4baba73c2e147ede7502"
        assert len(ma.masked_sites) == 133
        assert ma.masked_sites[0] == 1
        assert ma.masked_sites[-1] == 29903
