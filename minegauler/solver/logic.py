# May 2020, Lewis Gaul

"""
Solver logic.

"""

import itertools
import os
from collections import defaultdict
from pprint import pprint
from typing import Iterable, List, Tuple, Union

import numpy as np
import scipy.optimize
import sympy

from ..core.board import Board
from ..shared.types import CellContents, Coord_T


_debug = os.environ.get("SOLVER_DEBUG")

# A configuration type, where each value in the tuple corresponds to the number
# of mines in the corresponding group.
_Config_T = Tuple[int, ...]


class _MatrixAndVec:
    """Representation of simultaneous equations in matrix form."""

    def __init__(
        self, matrix: Union[np.ndarray, Iterable], vec: Union[np.ndarray, Iterable]
    ):
        self._matrix = np.array(matrix, int)
        self._vec = np.array(vec, int)

    def __str__(self):
        matrix_lines = [L[2:].rstrip("]") for L in str(self._matrix).splitlines()]
        vec_lines = [
            L[2:].rstrip("]") for L in str(np.array([self._vec]).T).splitlines()
        ]
        lines = (f"|{i} | {j} |" for i, j in zip(matrix_lines, vec_lines))
        return "\n".join(lines)

    @property
    def rows(self) -> int:
        return self._matrix.shape[0]

    @property
    def cols(self) -> int:
        return self._matrix.shape[1]

    def get_parts(self) -> Tuple[np.ndarray, np.ndarray]:
        return self._matrix, self._vec

    def unique_cols(self) -> Tuple["_MatrixAndVec", Tuple[int, ...]]:
        """Return a copy without duplicate columns, with column order unchanged."""
        cols = []
        inverse = []
        for i, col in enumerate(self._matrix.T):
            for j, c in enumerate(cols):
                if (c == col).all():
                    inverse.append(j)
                    break
            else:
                cols.append(col)
                inverse.append(len(cols) - 1)
        return self.__class__(np.array(cols).T, self._vec), tuple(inverse)

    def rref(self) -> Tuple["_MatrixAndVec", Tuple[int, ...], Tuple[int, ...]]:
        """Convert to Reduced-Row-Echelon Form."""
        sp_matrix, fixed_cols = sympy.Matrix(self._join_matrix_vec()).rref()
        free_cols = tuple(
            i for i in range(self._matrix.shape[1]) if i not in fixed_cols
        )
        np_matrix = np.array(sp_matrix, int)
        np_matrix = np_matrix[(np_matrix != 0).any(axis=1)]
        return self._from_joined_matrix_vec(np_matrix), fixed_cols, free_cols

    def filter_rows(self, rows) -> "_MatrixAndVec":
        return self.__class__(self._matrix[rows, :], self._vec[rows])

    def filter_cols(self, cols) -> "_MatrixAndVec":
        return self.__class__(self._matrix[:, cols], self._vec)

    def where_rows(self, func) -> "_MatrixAndVec":
        joined = self._join_matrix_vec()
        return self._from_joined_matrix_vec(joined[func(joined), :])

    def max_from_ineq(self) -> Tuple[int, ...]:
        max_vals = []
        for i in range(self.cols):
            c = [-int(i == j) for j in range(self.cols)]
            res = scipy.optimize.linprog(
                c, A_ub=self._matrix, b_ub=self._vec, method="revised simplex"
            )
            max_vals.append(int(res.x[i]))
        return tuple(max_vals)

    def reduce_vec_with_vals(self, vals) -> np.ndarray:
        return self._vec - np.matmul(self._matrix, vals)

    def _join_matrix_vec(self) -> np.ndarray:
        return np.c_[self._matrix, self._vec]

    @classmethod
    def _from_joined_matrix_vec(cls, joined: np.ndarray) -> "_MatrixAndVec":
        return cls(joined[:, :-1], joined[:, -1])


class Solver:
    """"""

    def __init__(self, board: Board, mines: int):
        self.board = board
        self.mines = mines

        self._unclicked_cells = [
            c for c in board.all_coords if type(board[c]) is not CellContents.Num
        ]
        self._number_cells = [
            c for c in board.all_coords if type(board[c]) is CellContents.Num
        ]

    @staticmethod
    def _iter_rectangular(max_values: _Config_T):
        yield from itertools.product(*[range(v + 1) for v in max_values])

    def _find_full_matrix(self) -> _MatrixAndVec:
        """
        Convert the board into a set of simultaneous equations, represented
        in matrix form.
        """
        matrix_arr = []
        vec = []
        for num_coord in self._number_cells:
            num_nbrs = self.board.get_nbrs(num_coord)
            if any([c in self._unclicked_cells for c in num_nbrs]):
                matrix_arr.append([num_nbrs.count(c) for c in self._unclicked_cells])
                vec.append(self.board[num_coord].num)
        matrix_arr.append([1] * len(self._unclicked_cells))
        vec.append(self.mines)
        return _MatrixAndVec(matrix_arr, vec)

    def _find_groups(self, matrix_inverse) -> List[List[Coord_T]]:
        groups = defaultdict(list)
        for cell_ind, group_ind in enumerate(matrix_inverse):
            groups[group_ind].append(self._unclicked_cells[cell_ind])
        return list(groups.values())

    def _find_configs(self) -> Iterable[_Config_T]:
        full_matrix = self._find_full_matrix()
        # if _debug:
        #     print("Full matrix:")
        #     print(full_matrix)
        #     print()

        groups_matrix, matrix_inverse = full_matrix.unique_cols()
        if _debug:
            print("Groups matrix:")
            print(groups_matrix)
            print()
        assert (groups_matrix._matrix[:, matrix_inverse] == full_matrix._matrix).all()

        groups = self._find_groups(matrix_inverse)
        if _debug:
            print(f"Groups ({len(groups)}):")
            pprint([(i, g if len(g) <= 8 else "...") for i, g in enumerate(groups)])
            print()

        rref_matrix, fixed_cols, free_cols = groups_matrix.rref()
        if _debug:
            print("RREF:")
            print(rref_matrix)
            print("Fixed:", fixed_cols)
            print("Free:", free_cols)
            print()

        # TODO: May be no need to bother with this?
        free_matrix = rref_matrix.filter_cols(free_cols)
        # if _debug:
        #     print("Free variables matrix:")
        #     print(free_matrix)
        #     print()

        free_vars_max = free_matrix.max_from_ineq()
        if _debug:
            print("Free variable max values:")
            print(free_vars_max)
            print()

        configs = set()
        cfg = [0 for _ in range(rref_matrix.cols)]
        for free_var_vals in self._iter_rectangular(free_vars_max):
            fixed_var_vals = free_matrix.reduce_vec_with_vals(free_var_vals)
            if not (fixed_var_vals >= 0).all():
                continue
            assert len(free_cols) == len(free_var_vals)
            assert len(fixed_cols) == len(fixed_var_vals)
            assert len(free_cols) + len(fixed_var_vals) == rref_matrix.cols
            assert not set(free_cols) & set(fixed_cols)
            for i, c in enumerate(free_cols):
                cfg[c] = free_var_vals[i]
            for i, c in enumerate(fixed_cols):
                cfg[c] = fixed_var_vals[i]
            configs.add(tuple(cfg))
        if _debug:
            print(f"Configurations ({len(configs)}):")
            print("\n".join(map(str, configs)))
            print()

        return configs


if __name__ == "__main__":
    x = CellContents.Unclicked.char
    board = Board.from_2d_array(
        [
            [x, 2, x, x, x],
            [x, x, x, x, x],
            [x, 3, x, x, x],
            [x, 2, x, 4, x],
            [x, x, x, x, x],
        ]
    )
    print("Using board:")
    print(board)

    s = Solver(board, 8)
    s._find_configs()
    m1 = s._find_full_matrix()
    m2 = m1.unique_cols()[0]
    m3 = m2.rref()[0]

    # fmt: off
    board2 = Board.from_2d_array([
    #    0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29
        [x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  #  0
        [x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  #  1
        [x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  #  2
        [x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  #  3
        [x, x, x, x, x, x, x, x, x, x, x, x, 4, 2, 2, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  #  4
        [x, x, x, x, x, x, x, x, x, x, 5, x, 2, 0, 2, 3, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  #  5
        [x, x, x, x, x, x, x, x, x, x, x, 3, 1, 0, 1, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  #  6
        [x, x, x, x, x, x, x, x, x, 6, x, 2, 0, 1, 2, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  #  7
        [x, x, x, x, x, x, 2, x, x, x, 4, 1, 0, 1, x, 2, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  #  8
        [x, x, x, x, 2, 1, 1, 1, 4, x, 3, 0, 0, 1, 1, 2, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  #  9
        [x, x, x, x, 2, 0, 0, 0, 1, 1, 2, 1, 1, 0, 1, 2, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  # 10
        [x, x, x, x, 2, 0, 0, 1, 1, 1, 2, x, 2, 0, 1, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  # 11
        [x, x, x, x, 1, 0, 0, 1, x, 2, 4, x, 3, 1, 3, 4, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  # 12
        [x, x, x, x, 2, 1, 1, 2, 2, 2, x, x, 2, 2, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  # 13
        [x, x, x, x, x, 1, 1, x, 1, 1, 2, 2, 1, 2, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  # 14
        [x, x, x, x, 2, 1, 1, 1, 1, 0, 0, 0, 0, 1, 2, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x],  # 15
    ])
    # fmt: on

    print("\n\n")
    print("Using board:")
    print(board2)

    np.set_printoptions(threshold=np.inf, linewidth=np.inf)
    s2 = Solver(board2, 99)
    m4 = s2._find_full_matrix()
    m5 = m4.unique_cols()[0]
    m6 = m5.rref()[0]

    print("\n\n")
    # s2.find_configs()
