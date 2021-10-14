from abc import abstractmethod
from fractions import Fraction as Frac
from typing import Any

import numpy as np
from sympy import Symbol, linsolve

from writer import Writer, MethodType


class ApproximationMethod:
    cost_table: np.ndarray
    assign_table: np.ndarray
    transportation_table: np.ndarray

    writer: Writer

    improvable: bool
    entrance_indicator: tuple

    rows: int
    columns: int

    demand_row: int
    supply_column: int

    most_assigned_row: int
    most_assigned_column: int

    v_row: int
    u_column: int

    deleted_rows: set
    deleted_cols: set

    assigned_indices: set
    unassigned_indices: set

    assignments_of_row: dict
    assignments_of_column: dict

    def __init__(self, file, method: MethodType):
        self.improvable = True
        self.most_assigned_row = -1
        self.most_assigned_column = -1
        self.entrance_indicator = tuple()
        self.unassigned_indices = set()
        self.assigned_indices = set()
        self.deleted_rows = set()
        self.deleted_cols = set()
        self.assignments_of_row = {self.most_assigned_row: -1}
        self.assignments_of_column = {self.most_assigned_column: -1}
        self.writer = Writer(method_type=method, filename=file.name)
        self.__create_cost_table(file)
        self.__balance_cost_table()
        self.__create_assign_table()
        self.__create_transportation_table()

    @abstractmethod
    def solve(self):
        pass

    def assign(self, assignment: Any, i: int, j: int, new_demmand_and_supply=True) -> None:

        self.assign_table[i][j] = assignment
        self.assigned_indices.add((i, j))
        self.unassigned_indices.discard((i, j))
        self.increment_assignments_of(i, j)

        if new_demmand_and_supply:
            self.assign_table[i][self.supply_column] -= assignment
            self.assign_table[self.demand_row][j] -= assignment

    def increment_assignments_of(self, i, j):
        i, j = i + 1, j + 1
        self.assignments_of_row[i] = self.assignments_of_row.get(i, 0) + 1
        self.assignments_of_column[j] = self.assignments_of_column.get(j, 0) + 1

        if self.assignments_of_row[i] > self.assignments_of_row[self.most_assigned_row]:
            self.most_assigned_row = i

        if self.assignments_of_column[j] > self.assignments_of_column[self.most_assigned_column]:
            self.most_assigned_column = j

    def unassign(self, i: int, j: int) -> None:
        self.unassigned_indices.add((i, j))
        self.decrement_assignments_of(i, j)

    def decrement_assignments_of(self, i, j):
        i, j = i + 1, j + 1
        self.assignments_of_row[i] = self.assignments_of_row.get(i, 0) - 1
        if self.most_assigned_row == i:
            self.most_assigned_row = max(self.assignments_of_row)

        if self.most_assigned_column:
            self.most_assigned_column = max(self.assignments_of_column)

    def improve(self):
        self.__find_dual_variables()
        self.__find_non_basic_indicators()

        while self.improvable:
            loop = self.__create_loop(start=[self.entrance_indicator])
            self.assign_from(loop)
            self.__find_dual_variables()
            self.__find_non_basic_indicators()

    def has_rows_and_columns_left(self) -> bool:
        return len(self.deleted_rows) != self.rows - 1 \
               and len(self.deleted_cols) != self.columns - 1

    def assign_from(self, loop):
        even_indices, odd_indices = loop[0::2], loop[1::2]

        def assignment(pos):
            return self.assign_table[pos]

        leaving_position = min(odd_indices, key=assignment)
        leaving_assignment = assignment(leaving_position)

        unassigned = set()
        for i, j in self.assigned_indices:
            if (i, j) in even_indices:
                self.assign_table[i][j] += leaving_assignment
            if (i, j) in odd_indices:
                self.assign_table[i][j] -= leaving_assignment
                can_be_unassigned = self.assign_table[i][j] == 0
                if can_be_unassigned:
                    unassigned.add((i, j))
                    self.unassign(i, j)
        self.assigned_indices -= unassigned
        self.assign(leaving_assignment, *self.entrance_indicator, new_demmand_and_supply=False)

    def __create_cost_table(self, file) -> None:
        # obtain first row of txt file and make it supply column
        supply = np.loadtxt(file, max_rows=1, delimiter=",", comments="\\n") + Frac()
        supply = supply.reshape((-1, 1))

        # obtain second row of txt file and make it demand row
        demand = np.loadtxt(file, max_rows=1, delimiter=",", comments="\\n") + Frac()
        demand = np.append(demand, "*").reshape((1, -1))

        # finally generate the cost_table with costs + demand + supply column
        costs = np.loadtxt(file, delimiter=",", comments="\\n") + Frac()
        self.cost_table = np.append(costs, values=supply, axis=1)
        self.cost_table = np.append(self.cost_table, values=demand, axis=0)

        # update attributes
        self.rows, self.columns = self.cost_table.shape
        self.demand_row, self.supply_column = self.rows - 1, self.columns - 1

        # file is no longer needed
        file.close()
        del file

    def __balance_cost_table(self) -> None:
        # balance the problem in case of different sums
        demand_sum = np.sum(self.cost_table[self.demand_row][:-1])
        supply_sum = np.sum(self.cost_table[:, self.supply_column][:-1])
        diff = abs(demand_sum - supply_sum)
        if demand_sum < supply_sum:
            self.__insert_fictional_demand(fictional_value=diff)
        elif supply_sum < demand_sum:
            self.__insert_fictional_supply(fictional_value=diff)
        else:
            pass

    def __insert_fictional_demand(self, fictional_value) -> None:
        # fictional/dummy demand row with zeros
        fictional_demand = [self.demand_row * [0] + [fictional_value]]
        self.cost_table = np.insert(self.cost_table, -1, values=fictional_demand, axis=1)
        self.columns += 1
        self.supply_column += 1

    def __insert_fictional_supply(self, fictional_value) -> None:
        # fictional/dummy supply column with zeros
        fictional_supply = self.supply_column * [0] + [fictional_value]
        self.cost_table = np.insert(self.cost_table, -1, values=fictional_supply, axis=0)
        self.rows += 1
        self.demand_row += 1

    def __create_assign_table(self) -> None:
        # fill table with zeros, supply cost column and demand row from cost_table
        self.assign_table = np.zeros((self.rows, self.columns), dtype=object)
        self.assign_table[:, self.supply_column] = self.cost_table[:, self.supply_column]
        self.assign_table[self.demand_row] = self.cost_table[self.demand_row]
        # assume all indices are unassigned
        self.unassigned_indices = {(i, j) for i in range(self.demand_row) for j in range(self.supply_column)}

    def __create_transportation_table(self) -> None:
        self.u_column = self.supply_column
        self.v_row = self.demand_row
        self.transportation_table = np.empty((self.rows, self.columns), dtype=object)
        self.transportation_table[self.v_row][self.u_column] = "*"

    def __create_loop(self, start):
        def find(loop):
            if len(loop) > 3:
                not_visited = start
                closable = len(self.find_neighbors(loop, not_visited)) == 1
                if closable:
                    return loop
            not_visited = list(self.assigned_indices - set(loop))
            possible_neighbors = self.find_neighbors(loop, not_visited)
            for neighbor in possible_neighbors:
                new_loop = find(loop + [neighbor])
                if new_loop:
                    return new_loop

        return find(loop=start)

    @staticmethod
    def find_neighbors(loop: list, not_visited: list):
        last_row, last_column = loop[-1]
        row_neighbors, column_neighbors = list(), list()
        for i, j in not_visited:
            if i == last_row:
                row_neighbors.append((i, j))
            if j == last_column:
                column_neighbors.append((i, j))
        if len(loop) < 2:
            return row_neighbors + column_neighbors
        else:
            previous_row, _ = loop[-2]
            is_row_move = previous_row == last_row
            if is_row_move:
                return column_neighbors
            return row_neighbors

    def __find_non_basic_indicators(self):
        # assume that it isn't improvable from the start
        self.improvable = False
        best_indicator = -np.inf
        for i, j in self.unassigned_indices:
            u = self.transportation_table[i][self.u_column]
            v = self.transportation_table[self.v_row][j]
            c = self.cost_table[i][j]
            nb_indicator = int(u + v - c)
            if nb_indicator > 0:
                self.improvable = True
                if nb_indicator > best_indicator:
                    best_indicator = nb_indicator
                    self.entrance_indicator = (i, j)
            self.transportation_table[i][j] = nb_indicator

    def __find_dual_variables(self):
        u_vars, v_vars = self.__find_equation_vars()
        equations = list()
        for i, j in self.assigned_indices:
            u = u_vars[i]
            v = v_vars[j]
            c = self.cost_table[i][j]
            eq = u + v - c
            equations.append(eq)
        solved = linsolve(equations, (u_vars + v_vars)).args[0]
        solved_u = list(map(int, solved[:self.u_column]))
        solved_v = list(map(int, solved[self.u_column:]))
        self.transportation_table[self.v_row, 0:self.u_column] = solved_v
        self.transportation_table[0:self.v_row, self.u_column] = solved_u

    def __find_equation_vars(self):
        if self.assignments_of_column[self.most_assigned_column] >= self.assignments_of_row[self.most_assigned_row]:
            zero_candidate = Symbol(f'V{self.most_assigned_column}')
        else:
            zero_candidate = Symbol(f'U{self.most_assigned_row}')

        v_vars = list()
        for i in range(1, self.rows):
            v = Symbol(f'V{i}')
            if v == zero_candidate:
                v_vars.append(0)
            else:
                v_vars.append(v)

        u_vars = list()
        for j in range(1, self.columns):
            u = Symbol(f'U{j}')
            if u == zero_candidate:
                u_vars.append(0)
            else:
                u_vars.append(u)

        return tuple(u_vars), tuple(v_vars)
