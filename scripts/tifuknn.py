"""TIFU-KNN baseline (Hu et al., SIGIR 2020, "Modeling Personalized Item
Frequency Information for Next-basket Recommendation").

1. User vector (personal item frequency, PIF). Past orders are cut into
   groups of `group_size`, counted from the most recent order, so only the
   oldest group can be smaller. With orders and groups indexed oldest to
   newest:
       group_j  = sum_i  r_b ** (m_j - i) * order_i / m_j
       user     = sum_j  r_g ** (K - j)   * group_j / K
   where order_i is the multi-hot basket, m_j the group size and K the
   number of groups. Recent orders and groups weigh more.
2. Find the `k_neighbors` nearest users (Euclidean distance, as in the
   paper's code) among the users of the same split.
3. Score = alpha * user + (1 - alpha) * mean(neighbours). Neighbours bring
   in products the user never bought.

No leakage: every vector, the user's and the neighbours', is built only
from orders before that user's own target order.
"""

import numpy as np
import polars as pl
import scipy.sparse as sp

KEYS = ["user_id", "t_order"]

# Tuned on val (20k users, 2026-10-22); never tune on test.
GROUP_SIZE = 3
R_B = 0.9
R_G = 0.6
K_NEIGHBORS = 900
ALPHA = 0.7


def order_weights(
    hist: pl.DataFrame, targets: pl.DataFrame, group_size: int, r_b: float, r_g: float
) -> pl.DataFrame:
    """Weight of each past order in the user vector of its target order."""
    past = (
        hist.join(targets.select(KEYS), on="user_id")
        .filter(pl.col("order_number") < pl.col("t_order"))
        .select(KEYS + ["order_number"])
        .unique()
    )
    m = group_size
    return (
        past.with_columns(
            n=pl.col("order_number").n_unique().over(KEYS),
            # 0 = most recent order.
            p=(pl.col("order_number").rank("ordinal", descending=True).over(KEYS) - 1),
        )
        .with_columns(
            g=pl.col("p") // m,           # 0 = most recent group
            q=pl.col("p") % m,            # 0 = most recent order in its group
            n_groups=(pl.col("n") + m - 1) // m,
        )
        .with_columns(
            m_g=pl.when(pl.col("g") == pl.col("n_groups") - 1)
            .then(pl.col("n") - m * (pl.col("n_groups") - 1))
            .otherwise(m)
        )
        .with_columns(
            w=(r_b ** pl.col("q")) / pl.col("m_g")
            * (r_g ** pl.col("g")) / pl.col("n_groups")
        )
        .select(KEYS + ["order_number", "w"])
    )


def user_vectors(
    hist: pl.DataFrame,
    targets: pl.DataFrame,
    group_size: int = GROUP_SIZE,
    r_b: float = R_B,
    r_g: float = R_G,
) -> tuple[pl.DataFrame, np.ndarray, sp.csr_matrix]:
    """Return (row keys, product ids per column, users x products matrix)."""
    w = order_weights(hist, targets, group_size, r_b, r_g)
    pif = (
        hist.select("user_id", "order_number", "product_id")
        .join(w, on=["user_id", "order_number"])
        .group_by(KEYS + ["product_id"])
        .agg(v=pl.col("w").sum())
    )
    rows = targets.select(KEYS).sort(KEYS).with_row_index("row")
    products = np.sort(pif["product_id"].unique().to_numpy())
    pif = pif.join(rows, on=KEYS)
    col = np.searchsorted(products, pif["product_id"].to_numpy())
    mat = sp.csr_matrix(
        (pif["v"].to_numpy(), (pif["row"].to_numpy(), col)),
        shape=(rows.height, len(products)),
    )
    return rows.drop("row"), products, mat


def nearest_neighbors(x: sp.csr_matrix, rows: slice, k: int) -> np.ndarray:
    """Indices of the k nearest other rows (Euclidean) for x[rows]."""
    sq = np.asarray(x.multiply(x).sum(axis=1)).ravel()
    dist = sq[rows, None] + sq[None, :] - 2 * (x[rows] @ x.T).toarray()
    r = np.arange(rows.start, rows.stop)
    dist[r - rows.start, r] = np.inf  # not self
    return np.argpartition(dist, k - 1, axis=1)[:, :k]


def top_n(scores: np.ndarray, products: np.ndarray, n: int) -> tuple[np.ndarray, ...]:
    """Top-n columns per row of a dense block: (row, product_id, rank).

    Products are sorted, so ties go to the smaller column = smaller product_id.
    Zero scores are never recommended.
    """
    n = min(n, scores.shape[1])
    idx = np.argpartition(-scores, n - 1, axis=1)[:, :n]
    vals = np.take_along_axis(scores, idx, axis=1)
    order = np.lexsort((idx, -vals), axis=1)
    idx = np.take_along_axis(idx, order, axis=1)
    vals = np.take_along_axis(vals, order, axis=1)
    rank = np.broadcast_to(np.arange(1, n + 1), idx.shape)
    row = np.broadcast_to(np.arange(len(idx))[:, None], idx.shape)
    keep = vals > 0
    return row[keep], products[idx[keep]], rank[keep]


def tifuknn(
    hist: pl.DataFrame,
    targets: pl.DataFrame,
    n: int,
    group_size: int = GROUP_SIZE,
    r_b: float = R_B,
    r_g: float = R_G,
    k_neighbors: int = K_NEIGHBORS,
    alpha: float = ALPHA,
    chunk: int = 1000,
    verbose: bool = False,
) -> pl.DataFrame:
    """Ranked top-n products per target order: user_id, t_order, product_id, rank.

    Rows are scored in chunks so the full users x products score matrix
    (hundreds of millions of non-zeros with k=900) is never built.
    """
    keys, products, x = user_vectors(hist, targets, group_size, r_b, r_g)
    n_rows = x.shape[0]
    k = min(k_neighbors, n_rows - 1)
    out = []
    for start in range(0, n_rows, chunk):
        rows = slice(start, min(start + chunk, n_rows))
        scores = alpha * x[rows].toarray()
        if k > 0:
            nbrs = nearest_neighbors(x, rows, k)
            m = len(nbrs)
            pick = sp.csr_matrix(
                (np.full(m * k, 1.0 / k), (np.repeat(np.arange(m), k), nbrs.ravel())),
                shape=(m, n_rows),
            )
            scores += (1 - alpha) * (pick @ x).toarray()
        r, p, rk = top_n(scores, products, n)
        out.append(pl.DataFrame({"row": (r + start).astype(np.uint32), "product_id": p, "rank": rk}))
        if verbose:
            print(f"  tifuknn {rows.stop}/{n_rows} users", flush=True)
    return (
        keys.with_row_index("row")
        .join(pl.concat(out), on="row")
        .select(KEYS + ["product_id", "rank"])
    )
