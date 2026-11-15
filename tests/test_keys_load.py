from backbone.keys import KeyPool, load_named


def test_only_named_keys_and_first_file_wins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("NIM_1=one\nexport NIM_2='two'\nOTHER=secret\n# NIM_3=nope\n")
    b.write_text("NIM_2=shadowed\nNIM_3=\"three\"\n")
    got = load_named(["NIM_1", "NIM_2", "NIM_3"], paths=[str(a), str(b)])
    assert got == {"NIM_1": "one", "NIM_2": "two", "NIM_3": "three"}
    assert "OTHER" not in load_named(["NIM_1"], paths=[str(a)])


def test_missing_file_is_empty(tmp_path):
    assert load_named(["NIM_1"], paths=[str(tmp_path / "nope")]) == {}


def test_explicit_env_is_untouched():
    p = KeyPool(["NIM_1", "NIM_2"], env={"NIM_1": "x"})
    assert p.names == ["NIM_1"]
