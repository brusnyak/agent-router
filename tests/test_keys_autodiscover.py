from backbone.keys import with_discovered


def test_new_nim_keys_join_without_config(tmp_path):
    env = tmp_path / ".env"
    env.write_text("NIM_1=a\nexport NIM_4=b\nNIM_10=c\nOTHER_KEY=x\nNIM_2=d\n")
    got = with_discovered(["NIM_1", "NIM_2"], paths=(str(env),), environ={})
    assert got == ["NIM_1", "NIM_2", "NIM_4", "NIM_10"]  # configured order kept, new numeric order, non-NIM ignored


def test_process_env_counts_and_no_duplicates(tmp_path):
    got = with_discovered(["NIM_3"], paths=(), environ={"NIM_3": "z", "NIM_5": "y"})
    assert got == ["NIM_3", "NIM_5"]
