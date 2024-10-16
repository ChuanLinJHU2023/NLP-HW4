#!/usr/bin/env python3
"""
Determine whether sentences are grammatical under a CFG, using Earley's algorithm.
(Starting from this basic recognizer, you should write a probabilistic parser
that reconstructs the highest-probability parse of each given sentence.)
"""

# Recognizer code by Arya McCarthy, Alexandra DeLucia, Jason Eisner, 2020-10, 2021-10.
# This code is hereby released to the public domain.

from __future__ import annotations
import argparse
import logging
import math
import tqdm
from dataclasses import dataclass
from pathlib import Path
from collections import Counter
from typing import Counter as CounterType, Iterable, List, Optional, Dict, Tuple, Union, final

from sympy.logic.boolalg import Boolean

log = logging.getLogger(Path(__file__).stem)  # For usage, see findsim.py in earlier assignment.


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "grammar", type=Path, help="Path to .gr file containing a PCFG'"
    )
    parser.add_argument(
        "sentences", type=Path, help="Path to .sen file containing tokenized input sentences"
    )
    parser.add_argument(
        "-s",
        "--start_symbol",
        type=str,
        help="Start symbol of the grammar (default is ROOT)",
        default="ROOT",
    )

    parser.add_argument(
        "--progress",
        action="store_true",
        help="Display a progress bar",
        default=False,
    )

    # for verbosity of logging
    parser.set_defaults(logging_level=logging.INFO)
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", "--verbose", dest="logging_level", action="store_const", const=logging.DEBUG
    )
    verbosity.add_argument(
        "-q", "--quiet", dest="logging_level", action="store_const", const=logging.WARNING
    )

    return parser.parse_args()


class EarleyChart:
    """A chart for Earley's algorithm."""

    def __init__(self, tokens: List[str], grammar: Grammar, progress: bool = False) -> None:
        """Create the chart based on parsing `tokens` with `grammar`.
        `progress` says whether to display progress bars as we parse."""
        self.tokens = tokens
        self.grammar = grammar
        self.progress = progress
        self.profile: CounterType[str] = Counter()
        self.cols: List[Agenda]
        self._run_earley()  # run Earley's algorithm to construct self.cols

    def accepted_with_item(self) -> Union[None, Item]:
        """Was the sentence accepted?
        That is, does the finished chart contain an item corresponding to a parse of the sentence?
        This method answers the recognition question, but not the parsing question."""
        final_item = None
        for item in self.cols[-1].all():  # the last column
            if (item.rule.lhs == self.grammar.start_symbol  # a ROOT item in this column
                    and item.next_symbol() is None  # that is complete
                    and item.start_position == 0):  # and started back at position 0
                final_item = item
                break
        return final_item

    def _run_earley(self) -> None:
        """Fill in the Earley chart."""
        # Initially empty column for each position in sentence
        self.cols = [Agenda() for _ in range(len(self.tokens) + 1)]

        # Start looking for ROOT at position 0
        self._predict(self.grammar.start_symbol, 0)

        # We'll go column by column, and within each column row by row.
        # Processing earlier entries in the column may extend the column
        # with later entries, which will be processed as well.
        #
        # The iterator over numbered columns is `enumerate(self.cols)`.
        # Wrapping this iterator in the `tqdm` call provides a progress bar.
        for i, column in tqdm.tqdm(enumerate(self.cols),
                                   total=len(self.cols),
                                   disable=not self.progress):
            log.debug("")
            log.debug(f"Processing items in column {i}")
            while column:  # while agenda isn't empty
                item = column.pop()  # dequeue the next unprocessed item
                next = item.next_symbol()
                if next is None:
                    # Attach this complete constituent to its customers
                    log.debug(f"{item} => ATTACH")
                    self._attach(item, i)
                elif self.grammar.is_nonterminal(next):
                    # Predict the nonterminal after the dot
                    log.debug(f"{item} => PREDICT")
                    self._predict(next, i)
                else:
                    # Try to scan the terminal after the dot
                    log.debug(f"{item} => SCAN")
                    self._scan(item, i)

    def _predict(self, nonterminal: str, position: int) -> None:
        """Start looking for this nonterminal at the given position.

        For predict, we <don't> need to consider move-down!!! (See B-2 Reprocessing for what is move-down)
        """
        for rule in self.grammar.expansions(nonterminal):
            new_item = Item(rule, dot_position=0, start_position=position)
            self.cols[position].push(new_item)

            new_tip = Tip(new_item)
            new_tip.initialize_when_predict()
            self.cols[position].update_tip_for_item(new_item, new_tip)

            log.debug(f"\tPredicted: {new_item} in column {position}")
            self.profile["PREDICT"] += 1

    def _scan(self, item: Item, position: int) -> None:
        """Attach the next word to this item that ends at position,
        if it matches what this item is looking for next.

        We call the "item" argument of this function the scanned item

        For scan, we <don't> need to consider move-down!!!!! (See B-2 Reprocessing for what is move-down)
        """
        if position < len(self.tokens) and self.tokens[position] == item.next_symbol():
            new_item = item.with_dot_advanced()
            self.cols[position + 1].push(new_item)

            new_tip = Tip(new_item)
            tip_of_scanned_item = self.cols[position].find_tip_for_item(item)
            new_tip.initialize_when_scan(tip_of_scanned_item)
            self.cols[position + 1].update_tip_for_item(new_item, new_tip)

            log.debug(f"\tScanned to get: {new_item} in column {position + 1}")
            self.profile["SCAN"] += 1

    def _attach(self, item: Item, position: int) -> None:
        """Attach this complete item to its customers in previous columns, advancing the
        customers' dots to create new items in this column.  (This operation is sometimes
        called "complete," but actually it attaches an item that was already complete.)

        We call the "item" argument of this function the attachment item or the attached item.
        Note that we also have a customer item

        For attach, we <do> need to consider move-down!!! (See B-2 Reprocessing for what is move-down)
        """
        mid = item.start_position  # start position of this item = end position of item to its left
        for customer in self.cols[mid].all():  # could you eliminate this inefficient linear search?
            if customer.next_symbol() == item.rule.lhs:
                new_item = customer.with_dot_advanced()
                if_old_item_exists = self.cols[position].push(new_item)

                new_tip = Tip(new_item)
                tip_of_attachment_item = self.cols[position].find_tip_for_item(item)
                tip_of_customer_item = self.cols[mid].find_tip_for_item(customer)
                new_tip.initialize_when_attach(tip_of_attachment_item, tip_of_customer_item, position)
                if_old_item_with_worse_weight = self.cols[position].update_tip_for_item(new_item, new_tip)

                if if_old_item_exists and if_old_item_with_worse_weight:
                    self.cols[position].move_down_item(new_item)

                log.debug(f"\tAttached to get: {new_item} in column {position}")
                self.profile["ATTACH"] += 1

    def find_tip_for_item_globally(self, item: Item, postion: Optional[int] = None) -> Tip:
        if postion is not None:
            agenda = self.cols[postion]
            if item in agenda.all():
                return agenda.find_tip_for_item(item)
        else:
            for i, agenda in enumerate(self.cols[::-1]):
                if item in agenda.all():
                    return agenda.find_tip_for_item(item)
        raise ValueError

    def pretty_print_item(self, item: Item, position: Optional[int] = None) -> str:
        tip = self.find_tip_for_item_globally(item, position)
        assert item.dot_position == len(item.rule.rhs) == len(tip.backpointers)
        lhs = item.rule.lhs
        result = "(" + f" {lhs}"
        for i in range(len(item.rule.rhs)):
            symbol = item.rule.rhs[i]
            if not self.grammar.is_nonterminal(symbol):
                # Terminal
                result += f" {symbol}"
            else:
                # Nonterminal, print recursively
                item_for_symbol, pos = tip.backpointers[i]
                assert item_for_symbol.rule.lhs == symbol
                result += f" {self.pretty_print_item(item_for_symbol, pos)}"
        result += ")"
        return result


# A dataclass is a class that provides some useful defaults for you. If you define
# the data that the class should hold, it will automatically make things like an
# initializer and an equality function.  This is just a shortcut.
# More info here: https://docs.python.org/3/library/dataclasses.html
# Using a dataclass here lets us declare that instances are "frozen" (immutable),
# and therefore can be hashed and used as keys in a dictionary.
@dataclass(frozen=True)
class Rule:
    """
    A grammar rule has a left-hand side (lhs), a right-hand side (rhs), and a weight.

    >>> r = Rule('S',('NP','VP'),3.14)
    >>> r
    S → NP VP
    >>> r.weight
    3.14
    >>> r.weight = 2.718
    Traceback (most recent call last):
    dataclasses.FrozenInstanceError: cannot assign to field 'weight'
    """
    lhs: str
    rhs: Tuple[str, ...]
    weight: float = 0.0

    def __repr__(self) -> str:
        """Complete string used to show this rule instance at the command line"""
        # Note: You might want to modify this to include the weight.
        return f"{self.lhs} → {' '.join(self.rhs)}"

# We particularly want items to be immutable, since they will be hashed and
# used as keys in a dictionary (for duplicate detection).
@dataclass(frozen=True)
class Item:
    """An item in the Earley parse chart, representing one or more subtrees
    that could yield a particular substring."""
    rule: Rule
    dot_position: int
    start_position: int

    # We don't store the end_position, which corresponds to the column
    # that the item is in, although you could store it redundantly for
    # debugging purposes if you wanted.

    def next_symbol(self) -> Optional[str]:
        """What's the next, unprocessed symbol (terminal, non-terminal, or None) in this partially matched rule?"""
        assert 0 <= self.dot_position <= len(self.rule.rhs)
        if self.dot_position == len(self.rule.rhs):
            return None
        else:
            return self.rule.rhs[self.dot_position]

    def with_dot_advanced(self) -> Item:
        if self.next_symbol() is None:
            raise IndexError("Can't advance the dot past the end of the rule")
        return Item(rule=self.rule, dot_position=self.dot_position + 1, start_position=self.start_position)

    def __repr__(self) -> str:
        """Human-readable representation string used when printing this item."""
        # Note: If you revise this class to change what an Item stores, you'll probably want to change this method too.
        DOT = "·"
        rhs = list(self.rule.rhs)  # Make a copy.
        rhs.insert(self.dot_position, DOT)
        dotted_rule = f"{self.rule.lhs} → {' '.join(rhs)}"
        return f"({self.start_position}, {dotted_rule})"  # matches notation on slides

Backpointer = Optional[Tuple[Item, int]]

class Tip:
    """
    We prepare a Tip object for each Item object.
    For each item, its tip helps to indicate the weight and backpointers for this item.
    """
    def __init__(self, item) -> None:
        self.item: Item = item    # For what item are we initializing this tip?
        self.weight: Union[int, None] = None
        self.backpointers: list[Backpointer] = list()

    def initialize_when_predict(self):
        # In this case, self.item is an item added to agenda by predict
        self.weight = self.item.rule.weight
        assert len(self.backpointers) == self.item.dot_position

    def initialize_when_scan(self, tip_of_scanned_item : Tip):
        # In this case, self.item is an item added to agenda by scan
        self.weight = tip_of_scanned_item.weight
        self.backpointers = tip_of_scanned_item.backpointers + [None] # The backpointer for a terminal is just a None
        assert len(self.backpointers) == self.item.dot_position

    def initialize_when_attach(self, tip_of_attachment_item : Tip, tip_of_customer_item: Tip, position: int):
        # In this case, self.item is an item added to agenda by attach
        assert len(tip_of_attachment_item.item.rule.rhs) == tip_of_attachment_item.item.dot_position == len(tip_of_attachment_item.backpointers) # assure that attachment item is complete
        self.weight = tip_of_customer_item.weight + tip_of_attachment_item.weight
        self.backpointers = tip_of_customer_item.backpointers + [(tip_of_attachment_item.item, position)] # The backpointer for a non-terminal is a item that is complete
        assert len(self.backpointers) == self.item.dot_position

def move_down(lst, i):
    """
    Move down the i-th element of the lst
    >>> lst = [5,8,7,2,3,10]
    >>> move_down(lst,2)
    [5, 8, 2, 3, 10, 7]
    """
    assert i<len(lst)
    new_lst = lst[:i] + lst[i+1:] + [lst[i]]
    return new_lst

class Agenda:
    """An agenda of items that need to be processed.  Newly built items
    may be enqueued for processing by `push()`, and should eventually be
    dequeued by `pop()`.

    This implementation of an agenda also remembers which items have
    been pushed before, even if they have subsequently been popped.
    This is because already popped items must still be found by
    duplicate detection and as customers for attach.

    (In general, AI algorithms often maintain a "closed list" (or
    "chart") of items that have already been popped, in addition to
    the "open list" (or "agenda") of items that are still waiting to pop.)

    In Earley's algorithm, each end position has its own agenda -- a column
    in the parse chart.  (This contrasts with agenda-based parsing, which uses
    a single agenda for all items.)

    Standardly, each column's agenda is implemented as a FIFO queue
    with duplicate detection, and that is what is implemented here.
    However, other implementations are possible -- and could be useful
    when dealing with weights, backpointers, and optimizations.

    """

    def __init__(self) -> None:
        self._items: List[Item] = []  # list of all items that were *ever* pushed
        self._index: Dict[Item, int] = {}  # stores index of an item if it was ever pushed
        self._tips: Dict[Item, Tip] = {} # stores the tip of an item if it was ever pushed
        self._next = 0  # index of first item that has not yet been popped

        # Note: There are other possible designs.  For example, self._index doesn't really
        # have to store the index; it could be changed from a dictionary to a set.
        #
        # However, we provided this design because there are multiple reasonable ways to extend
        # this design to store weights and backpointers.  That additional information could be
        # stored either in self._items or in self._index.

    def __len__(self) -> int:
        """Returns number of items that are still waiting to be popped.
        Enables `len(my_agenda)`."""
        return len(self._items) - self._next

    def push(self, item: Item) -> bool:
        """Add (enqueue) the item, unless it was previously added."""
        if_old_item_exists = item in self._index
        if item not in self._index:  # O(1) lookup in hash table
            self._items.append(item)
            self._index[item] = len(self._items) - 1
        return if_old_item_exists

    def pop(self) -> Item:
        """Returns one of the items that was waiting to be popped (dequeued).
        Raises IndexError if there are no items waiting."""
        if len(self) == 0:
            raise IndexError
        item = self._items[self._next]
        self._next += 1
        return item

    def all(self) -> Iterable[Item]:
        """Collection of all items that have ever been pushed, even if
        they've already been popped."""
        return self._items

    def __repr__(self):
        """Provide a human-readable string REPResentation of this Agenda."""
        next = self._next
        return f"{self.__class__.__name__}({self._items[:next]}; {self._items[next:]})"

    def update_tip_for_item(self, item: Item, tip: Tip):
        assert item in self._index
        if_old_item_with_worse_weight = False
        if item not in self._tips:
            self._tips[item] = tip  # Create the tip for existing item
        else:
            old_tip = self._tips[item]
            # This difference will affect permissive.par!!!!!!!!!!!!!!!!!!
            # if tip.weight < old_tip.weight:
            if tip.weight <= old_tip.weight:
                self._tips[item] = tip # Renew the tip for existing item
                if_old_item_with_worse_weight = True
        assert len(self._index) == len(self._items)
        return if_old_item_with_worse_weight

    def move_down_item(self, item: Item):
        # ******Move Down an Item For Reprocessing******* See B.2 for what is reprocessing!!
        # Remember that self._next is the index of first item that has not yet been popped
        log.debug(f"We are moving down an item {item}")
        log.debug(f"Before move-down, the index of items are: {self._index}")
        log.debug(f"Before move-down, the index of first not-popped item is: {self._next}")
        assert item in self._index
        if not self._index[item] < self._next: # no need to move down
            return
        index = self._index[item]
        move_down(self._items, index)
        for item_ in self._index:
            if self._index[item_] > index:
                self._index[item_] -= 1
        self._index[item] = len(self._items) - 1
        self._next -= 1 # We need to move up the pointer!
        assert len(self._index) == len(self._items)
        log.debug(f"After move-down, the index of items are: {self._index}")
        log.debug(f"After move-down, the index of first not-popped item : {self._next}")

    def find_tip_for_item(self, item: Item) -> Tip:
        assert item in self._tips
        return self._tips[item]



class Grammar:
    """Represents a weighted context-free grammar."""

    def __init__(self, start_symbol: str, *files: Path) -> None:
        """Create a grammar with the given start symbol,
        adding rules from the specified files if any."""
        self.start_symbol = start_symbol
        self._expansions: Dict[str, List[Rule]] = {}  # maps each LHS to the list of rules that expand it
        # Read the input grammar files
        for file in files:
            self.add_rules_from_file(file)

    def add_rules_from_file(self, file: Path) -> None:
        """Add rules to this grammar from a file (one rule per line).
        Each rule is preceded by a normalized probability p,
        and we take -log2(p) to be the rule's weight."""
        with open(file, "r") as f:
            for line in f:
                # remove any comment from end of line, and any trailing whitespace
                line = line.split("#")[0].rstrip()
                # skip empty lines
                if line == "":
                    continue
                # Parse tab-delimited line of format <probability>\t<lhs>\t<rhs>
                _prob, lhs, _rhs = line.split("\t")
                prob = float(_prob)
                rhs = tuple(_rhs.split())
                rule = Rule(lhs=lhs, rhs=rhs, weight=-math.log2(prob))
                if lhs not in self._expansions:
                    self._expansions[lhs] = []
                self._expansions[lhs].append(rule)

    def expansions(self, lhs: str) -> Iterable[Rule]:
        """Return an iterable collection of all rules with a given lhs"""
        return self._expansions[lhs]

    def is_nonterminal(self, symbol: str) -> bool:
        """Is symbol a nonterminal symbol?"""
        return symbol in self._expansions

def weight_to_prob(weight):
    prob = 2**(-weight)
    assert prob>=0 and prob<=1
    return prob

def main():
    # Parse the command-line arguments
    args = parse_args()
    logging.basicConfig(level=args.logging_level)

    grammar = Grammar(args.start_symbol, args.grammar)

    with open(args.sentences) as f:
        for sentence in f.readlines():
            sentence = sentence.strip()
            if sentence != "":  # skip blank lines
                # analyze the sentence
                log.debug("=" * 70)
                log.debug(f"Parsing sentence: {sentence}")
                chart = EarleyChart(sentence.split(), grammar, progress=args.progress)
                final_item = chart.accepted_with_item()
                # log.info(sentence)
                if final_item is None:
                    # log.info("This sentence is rejected!")
                    print("NONE")
                else:
                    print(chart.pretty_print_item(final_item))
                    print(chart.cols[-1].find_tip_for_item(final_item).weight)
                    # log.info(f"This sentence is accepted with prob {weight_to_prob(chart.cols[-1].find_tip_for_item(final_item).weight)}")
                    # log.info(f"This sentence is accepted with weight {chart.cols[-1].find_tip_for_item(final_item).weight}")

if __name__ == "__main__":
    import doctest

    doctest.testmod(verbose=False)  # run tests
    main()
