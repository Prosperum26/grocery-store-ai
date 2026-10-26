import numpy as np
import polars as pl
import pytest

from scripts.final_eval import check_not_run
from scripts.train_lgbm import rank_top


def test_rank_top_breaks_ties_by_product_id_and_cuts_at_n():
    df = pl.DataFrame({"user_id": [1] * 4 + [2] * 2, "t_order": [5] * 6,
                       "product_id": [4, 3, 2, 1, 7, 8]})
    top = rank_top(df, np.array([0.5, 0.5, 0.9, 0.1, 0.2, 0.3]), n=3)
    u1 = top.filter(pl.col("user_id") == 1).sort("rank")
    assert u1["product_id"].to_list() == [2, 3, 4]    # 3 before 4 on the tie
    assert u1["rank"].to_list() == [1, 2, 3]
    u2 = top.filter(pl.col("user_id") == 2).sort("rank")
    assert u2["product_id"].to_list() == [8, 7]        # ranks restart per order


def test_final_eval_refuses_second_run(tmp_path):
    check_not_run(tmp_path / "missing.json")           # no result yet: ok
    done = tmp_path / "final_test.json"
    done.write_text("{}")
    with pytest.raises(SystemExit):
        check_not_run(tmp_path / "missing.json", done)
