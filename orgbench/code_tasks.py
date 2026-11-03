"""Tool-style code tasks with deterministic public/private tests.

Candidate Python is interpreted as a deliberately small AST language: it is
never passed to exec/eval/compile, imported, or executed by the Python VM. It
runs in a hard-timeout, memory-limited subprocess as defense in depth, not a
production arbitrary-code security sandbox. Do not replace it with direct exec.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import random
import time


class CandidateError(ValueError):
    """A candidate uses unsupported syntax, fails a check, or exhausts fuel."""


class _Return(Exception):
    def __init__(self, value):
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Env:
    def __init__(self, parent=None):
        self.values = {}
        self.parent = parent

    def get(self, name):
        if name in self.values:
            return self.values[name]
        if self.parent is not None:
            return self.parent.get(name)
        raise CandidateError(f"Undefined name: {name}")


class _Builtin:
    def __init__(self, name):
        self.name = name


class _Method:
    def __init__(self, obj, name):
        self.obj, self.name = obj, name


class _Function:
    def __init__(self, node, env, defaults):
        self.node, self.env, self.defaults = node, env, defaults


class _Generator:
    """Interpreter-owned lazy iterator; no attributes are exposed to candidates."""
    def __init__(self, iterator):
        self.iterator = iterator

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)


_METHODS = {
    dict: {"get", "items", "keys", "values", "copy", "pop", "update", "setdefault", "clear"},
    list: {"append", "extend", "pop", "remove", "sort", "reverse", "copy", "index", "count", "clear"},
    set: {"add", "discard", "remove", "copy", "union", "intersection", "difference", "issubset", "clear"},
    str: {"lower", "upper", "strip", "lstrip", "rstrip", "split", "join", "startswith", "endswith", "isdigit", "isalnum", "replace", "count", "find"},
    tuple: {"count", "index"},
}
_BUILTIN_NAMES = ("len", "range", "enumerate", "zip", "sorted", "reversed", "list", "dict", "set", "tuple",
                  "str", "int", "float", "bool", "type", "isinstance", "sum", "min", "max", "abs", "round", "all", "any")
_ALLOWED_AST = {
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign, ast.AugAssign,
    ast.Expr, ast.If, ast.For, ast.While, ast.Break, ast.Continue, ast.Pass, ast.Delete,
    ast.Name, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice,
    ast.Attribute, ast.Call, ast.keyword, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp,
    ast.GeneratorExp, ast.comprehension, ast.IfExp, ast.BoolOp, ast.BinOp, ast.UnaryOp,
    ast.Compare, ast.JoinedStr, ast.FormattedValue, ast.Starred,
    ast.Load, ast.Store, ast.Del, ast.And, ast.Or, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.FloorDiv, ast.Mod, ast.Pow, ast.BitAnd, ast.BitOr, ast.BitXor,
    ast.Not, ast.UAdd, ast.USub, ast.Invert, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
    ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
}

ALLOWED_PYTHON_SUBSET = (
    "Define solve(payload); helper def/lambda and literal module constants are allowed. "
    "Use plain dict/list/set/tuple/string/integer/float/bool/None, assignment, if, for, while, "
    "break/continue, return, comprehensions, slicing, arithmetic and comparisons. "
    "Builtins: " + ", ".join(_BUILTIN_NAMES) + ". "
    "Common container methods (get/items/keys/values/append/extend/pop/update/setdefault/"
    "add/discard/sort/copy) and basic string methods (lower/upper/strip/split/join/"
    "startswith/endswith/replace) are supported. sorted(...,key=lambda x:...,reverse=...) is allowed. "
    "No imports, classes, exceptions/try, decorators, global/nonlocal, with, async, yield, "
    "eval/exec/compile, file/network/process access, print, dunder names or arbitrary attributes. "
    "Only function definitions and literal constant assignments at module level. "
    "Bounds: source <=24000 characters; AST <=8000 nodes; container <=4096 items; "
    "string/output <=65536 characters; recursion <=32; fuel and 2-second validation deadline."
)


def _parse_source(source):
    if not isinstance(source, str) or not source.strip():
        raise CandidateError("source must be a nonempty Python string")
    if len(source) > 24000:
        raise CandidateError("source exceeds 24000 characters")
    try:
        tree = ast.parse(source, mode="exec")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise CandidateError(f"Invalid Python syntax ({type(exc).__name__})") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > 8000:
        raise CandidateError("AST node limit exceeded")
    method_names = set().union(*_METHODS.values())
    for node in nodes:
        if type(node) not in _ALLOWED_AST:
            raise CandidateError(f"Unsupported syntax: {type(node).__name__}")
        if isinstance(node, (ast.Name, ast.arg)):
            name = node.id if isinstance(node, ast.Name) else node.arg
            if "__" in name:
                raise CandidateError("Dunder names are forbidden")
        if isinstance(node, ast.FunctionDef):
            if "__" in node.name or node.decorator_list:
                raise CandidateError("Decorators and dunder function names are forbidden")
        if isinstance(node, ast.Attribute) and node.attr not in method_names:
            raise CandidateError(f"Unsupported attribute: {node.attr}")
        if isinstance(node, ast.comprehension) and node.is_async:
            raise CandidateError("Async comprehensions are forbidden")
        if isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            raise CandidateError("Formatted-string format specifications are unsupported")
        if isinstance(node, ast.Constant):
            if type(node.value) not in (str, int, float, bool, type(None)):
                raise CandidateError("Unsupported literal")
            if type(node.value) is int and node.value.bit_length() > 256:
                raise CandidateError("Integer literal too large")
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.FunctionDef):
            continue
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError, RecursionError):
                raise CandidateError("Module assignments must be literal constants") from None
            if any(not isinstance(target, ast.Name) for target in node.targets):
                raise CandidateError("Module constant assignment needs a simple name")
            _check_value(value)
            continue
        raise CandidateError("Only functions and literal constants are allowed at module level")
    if not any(isinstance(node, ast.FunctionDef) and node.name == "solve" for node in tree.body):
        raise CandidateError("Missing solve(payload) function")
    return tree


def _check_value(value, depth=0):
    if depth > 40:
        raise CandidateError("Value nesting limit exceeded")
    if isinstance(value, (str, bytes)) and len(value) > 65536:
        raise CandidateError("String limit exceeded")
    if isinstance(value, (dict, list, tuple, set, range)) and len(value) > 4096:
        raise CandidateError("Container limit exceeded")
    if type(value) is int and value.bit_length() > 2048:
        raise CandidateError("Integer size limit exceeded")
    if type(value) is float and not math.isfinite(value):
        raise CandidateError("Nonfinite float")
    return value


class _Interpreter:
    """No host object capabilities are supplied to model-controlled AST nodes."""

    def __init__(self, tree, deadline=None, fuel=250000):
        self.deadline = deadline if deadline is not None else time.monotonic() + 2.0
        self.fuel = fuel
        self.ticks = 0
        self.depth = 0
        self.allocation_budget = 200000
        self.env = _Env()
        self.builtins = {name: _Builtin(name) for name in _BUILTIN_NAMES}
        self.builtin_none_type = _Builtin("NoneType")
        self.env.values.update(self.builtins)
        self.block(tree.body, self.env)

    def allocate(self, value):
        _check_value(value)
        if type(value) in (dict, list, tuple, set, str):
            self.allocation_budget -= len(value)
            if self.allocation_budget < 0:
                raise CandidateError("Aggregate allocation budget exhausted")
        return value

    def tick(self):
        self.fuel -= 1
        self.ticks += 1
        if self.fuel < 0:
            raise CandidateError("Instruction fuel exhausted")
        if self.ticks % 128 == 0 and time.monotonic() > self.deadline:
            raise CandidateError("Validation timeout")

    def iterable(self, value):
        if type(value) not in (list, tuple, set, dict, str, range, _Generator):
            raise CandidateError("Only bounded builtin containers are iterable")
        _check_value(value)
        return value

    def assign(self, target, value, env):
        self.tick()
        if isinstance(target, ast.Name):
            env.values[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            seq = list(self.iterable(value))
            starred = [i for i, item in enumerate(target.elts) if isinstance(item, ast.Starred)]
            if len(starred) > 1:
                raise CandidateError("Multiple starred assignments")
            if starred:
                k = starred[0]
                if len(seq) < len(target.elts) - 1:
                    raise CandidateError("Unpacking length mismatch")
                tail = len(target.elts) - k - 1
                for i, item in enumerate(target.elts[:k]):
                    self.assign(item, seq[i], env)
                self.assign(target.elts[k].value, seq[k:len(seq) - tail if tail else len(seq)], env)
                for item, val in zip(target.elts[k + 1:], seq[len(seq) - tail:]):
                    self.assign(item, val, env)
            else:
                if len(seq) != len(target.elts):
                    raise CandidateError("Unpacking length mismatch")
                for item, val in zip(target.elts, seq):
                    self.assign(item, val, env)
        elif isinstance(target, ast.Subscript):
            obj, index = self.expression(target.value, env), self.expression(target.slice, env)
            if type(obj) not in (dict, list):
                raise CandidateError("Assignment requires dict/list")
            obj[index] = value
            _check_value(obj)
        else:
            raise CandidateError("Unsupported assignment target")

    def block(self, statements, env):
        for node in statements:
            self.statement(node, env)

    def statement(self, node, env):
        self.tick()
        if isinstance(node, ast.FunctionDef):
            env.values[node.name] = _Function(node, env, [self.expression(d, env) for d in node.args.defaults])
        elif isinstance(node, ast.Return):
            raise _Return(self.expression(node.value, env) if node.value is not None else None)
        elif isinstance(node, ast.Assign):
            value = self.expression(node.value, env)
            for target in node.targets:
                self.assign(target, value, env)
        elif isinstance(node, ast.AugAssign):
            # Resolve receiver and index once, before the right-hand side.
            if isinstance(node.target, ast.Subscript):
                obj = self.expression(node.target.value, env)
                index = self.expression(node.target.slice, env)
                if type(obj) not in (dict, list):
                    raise CandidateError("Augmented assignment requires dict/list")
                old = obj[index]
                value = self.binary(node.op, old, self.expression(node.value, env))
                obj[index] = value
                _check_value(obj)
            else:
                value = self.binary(node.op, self.expression(node.target, env), self.expression(node.value, env))
                self.assign(node.target, value, env)
        elif isinstance(node, ast.Expr):
            self.expression(node.value, env)
        elif isinstance(node, ast.If):
            self.block(node.body if self.expression(node.test, env) else node.orelse, env)
        elif isinstance(node, (ast.For, ast.While)):
            broke = False
            iterator = iter(self.iterable(self.expression(node.iter, env))) if isinstance(node, ast.For) else None
            while True:
                self.tick()
                if isinstance(node, ast.For):
                    try:
                        value = next(iterator)
                    except StopIteration:
                        break
                    self.assign(node.target, value, env)
                elif not self.expression(node.test, env):
                    break
                try:
                    self.block(node.body, env)
                except _Continue:
                    continue
                except _Break:
                    broke = True
                    break
            if not broke:
                self.block(node.orelse, env)
        elif isinstance(node, ast.Break):
            raise _Break()
        elif isinstance(node, ast.Continue):
            raise _Continue()
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    raise CandidateError("Only dict/list item deletion supported")
                obj, index = self.expression(target.value, env), self.expression(target.slice, env)
                if type(obj) not in (dict, list):
                    raise CandidateError("Invalid deletion target")
                del obj[index]
        elif not isinstance(node, ast.Pass):
            raise CandidateError(f"Unsupported statement: {type(node).__name__}")

    def binary(self, op, left, right):
        self.tick()
        if isinstance(op, ast.Mult):
            seq, count = (left, right) if isinstance(left, (str, list, tuple)) else (right, left)
            if isinstance(seq, (str, list, tuple)) and type(count) is int:
                cap = 65536 if isinstance(seq, str) else 4096
                if len(seq) * max(0, count) > cap:
                    raise CandidateError("Repetition size limit exceeded")
        if isinstance(op, ast.Pow) and (type(right) not in (int, float) or abs(right) > 32
                                       or type(left) not in (int, float) or abs(left) > 10**18):
            raise CandidateError("Exponentiation limit exceeded")
        if isinstance(op, ast.Mod) and isinstance(left, str):
            raise CandidateError("Percent string formatting unsupported")
        if isinstance(op, ast.Add): result = left + right
        elif isinstance(op, ast.Sub): result = left - right
        elif isinstance(op, ast.Mult): result = left * right
        elif isinstance(op, ast.Div): result = left / right
        elif isinstance(op, ast.FloorDiv): result = left // right
        elif isinstance(op, ast.Mod): result = left % right
        elif isinstance(op, ast.Pow): result = left ** right
        elif isinstance(op, ast.BitAnd): result = left & right
        elif isinstance(op, ast.BitOr): result = left | right
        elif isinstance(op, ast.BitXor): result = left ^ right
        else: raise CandidateError("Unsupported binary operator")
        return self.allocate(result)

    def compare(self, op, left, right):
        if isinstance(op, ast.Eq): return left == right
        if isinstance(op, ast.NotEq): return left != right
        if isinstance(op, ast.Lt): return left < right
        if isinstance(op, ast.LtE): return left <= right
        if isinstance(op, ast.Gt): return left > right
        if isinstance(op, ast.GtE): return left >= right
        if isinstance(op, ast.Is): return left is right
        if isinstance(op, ast.IsNot): return left is not right
        if isinstance(op, ast.In): return left in right
        if isinstance(op, ast.NotIn): return left not in right
        raise CandidateError("Unsupported comparison")

    def _comprehension(self, node, env):
        local = _Env(env)
        produced = 0
        def visit(index):
            nonlocal produced
            self.tick()
            if index == len(node.generators):
                produced += 1
                if produced > 4096:
                    raise CandidateError("Comprehension size limit exceeded")
                value = ((self.expression(node.key, local), self.expression(node.value, local))
                         if isinstance(node, ast.DictComp) else self.expression(node.elt, local))
                yield value
                return
            gen = node.generators[index]
            for value in self.iterable(self.expression(gen.iter, local)):
                self.assign(gen.target, value, local)
                if all(self.expression(test, local) for test in gen.ifs):
                    yield from visit(index + 1)
        if isinstance(node, ast.GeneratorExp):
            return _Generator(visit(0))
        result = list(visit(0))
        if isinstance(node, ast.DictComp): return self.allocate(dict(result))
        if isinstance(node, ast.SetComp): return self.allocate(set(result))
        return self.allocate(result)

    def expression(self, node, env):
        self.tick()
        if isinstance(node, ast.Constant): return _check_value(node.value)
        if isinstance(node, ast.Name): return env.get(node.id)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            vals = []
            for item in node.elts:
                if isinstance(item, ast.Starred): vals.extend(self.iterable(self.expression(item.value, env)))
                else: vals.append(self.expression(item, env))
                _check_value(vals)
            return self.allocate(tuple(vals) if isinstance(node, ast.Tuple) else set(vals) if isinstance(node, ast.Set) else vals)
        if isinstance(node, ast.Dict):
            value = {}
            for key, item in zip(node.keys, node.values):
                if key is None: value.update(self.expression(item, env))
                else: value[self.expression(key, env)] = self.expression(item, env)
                _check_value(value)
            return self.allocate(value)
        if isinstance(node, ast.Subscript):
            obj, index = self.expression(node.value, env), self.expression(node.slice, env)
            if type(obj) not in (dict, list, tuple, str, range):
                raise CandidateError("Only builtin containers may be indexed")
            return _check_value(obj[index])
        if isinstance(node, ast.Slice):
            return slice(self.expression(node.lower, env) if node.lower else None,
                         self.expression(node.upper, env) if node.upper else None,
                         self.expression(node.step, env) if node.step else None)
        if isinstance(node, ast.Attribute):
            obj = self.expression(node.value, env)
            if node.attr not in _METHODS.get(type(obj), set()):
                raise CandidateError("Method not permitted on this type")
            return _Method(obj, node.attr)
        if isinstance(node, ast.Call):
            func = self.expression(node.func, env)
            args, kwargs = [], {}
            for arg in node.args:
                if isinstance(arg, ast.Starred): args.extend(self.iterable(self.expression(arg.value, env)))
                else: args.append(self.expression(arg, env))
            for item in node.keywords:
                if item.arg is None: kwargs.update(self.expression(item.value, env))
                else: kwargs[item.arg] = self.expression(item.value, env)
            return self.call(func, args, kwargs)
        if isinstance(node, ast.Lambda):
            return _Function(node, env, [self.expression(d, env) for d in node.args.defaults])
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return self._comprehension(node, env)
        if isinstance(node, ast.IfExp):
            return self.expression(node.body if self.expression(node.test, env) else node.orelse, env)
        if isinstance(node, ast.BoolOp):
            for item in node.values:
                value = self.expression(item, env)
                if isinstance(node.op, ast.And) and not value: return value
                if isinstance(node.op, ast.Or) and value: return value
            return value
        if isinstance(node, ast.BinOp):
            return self.binary(node.op, self.expression(node.left, env), self.expression(node.right, env))
        if isinstance(node, ast.UnaryOp):
            value = self.expression(node.operand, env)
            if isinstance(node.op, ast.Not): return not value
            if isinstance(node.op, ast.USub): return _check_value(-value)
            if isinstance(node.op, ast.UAdd): return _check_value(+value)
            if isinstance(node.op, ast.Invert): return _check_value(~value)
        if isinstance(node, ast.Compare):
            left = self.expression(node.left, env)
            for op, item in zip(node.ops, node.comparators):
                right = self.expression(item, env)
                if not self.compare(op, left, right): return False
                left = right
            return True
        if isinstance(node, ast.JoinedStr):
            return _check_value("".join(str(self.expression(v, env)) for v in node.values))
        if isinstance(node, ast.FormattedValue):
            value = self.expression(node.value, env)
            if type(value) not in (str, int, float, bool, type(None)):
                raise CandidateError("Formatted-string conversion only supports scalars")
            return _check_value(repr(value) if node.conversion == 114 else str(value))
        raise CandidateError(f"Unsupported expression: {type(node).__name__}")

    def call(self, func, args, kwargs):
        self.tick()
        if isinstance(func, _Builtin):
            return self.allocate(self.builtin(func.name, args, kwargs))
        if isinstance(func, _Method):
            return self.allocate(self.method(func.obj, func.name, args, kwargs))
        if not isinstance(func, _Function):
            raise CandidateError("Only interpreted functions and approved builtins can be called")
        self.depth += 1
        if self.depth > 32:
            raise CandidateError("Recursion limit exceeded")
        try:
            spec = func.node.args
            params = [a.arg for a in spec.posonlyargs + spec.args]
            if spec.kwonlyargs or spec.kwarg or spec.vararg:
                raise CandidateError("Variadic/keyword-only function parameters unsupported")
            if len(args) > len(params):
                raise CandidateError("Too many arguments")
            local = _Env(func.env)
            for name, value in zip(params, args): local.values[name] = value
            for name, value in kwargs.items():
                if name not in params or name in local.values: raise CandidateError("Invalid keyword argument")
                local.values[name] = value
            for name, value in zip(params[len(params) - len(func.defaults):], func.defaults):
                local.values.setdefault(name, value)
            if any(name not in local.values for name in params): raise CandidateError("Missing argument")
            if isinstance(func.node, ast.Lambda): return self.expression(func.node.body, local)
            try:
                self.block(func.node.body, local)
            except _Return as result:
                return result.value
            return None
        finally:
            self.depth -= 1

    def builtin(self, name, args, kwargs):
        if name == "type":
            return self.builtin_none_type if args[0] is None else self.builtins.get(type(args[0]).__name__)
        if name == "NoneType":
            if args or kwargs: raise CandidateError("NoneType takes no arguments")
            return None
        if name == "isinstance":
            wanted = args[1] if isinstance(args[1], tuple) else (args[1],)
            return any(isinstance(t, _Builtin) and
                       (type(args[0]).__name__ == t.name or t.name == "int" and type(args[0]) is bool)
                       for t in wanted)
        if name in ("sorted", "min", "max"):
            key = kwargs.pop("key", None)
            if key is not None and not isinstance(key, (_Function, _Builtin, _Method)):
                raise CandidateError("Invalid key function")
            options = dict(kwargs)
            if key is not None: options["key"] = lambda value: self.call(key, [value], {})
            if name == "sorted": return _check_value(sorted(self.iterable(args[0]), **options))
            values = list(self.iterable(args[0])) if len(args) == 1 else args
            return (min if name == "min" else max)(values, **options)
        if name == "range": return _check_value(range(*args, **kwargs))
        if name == "enumerate": return _check_value(list(enumerate(self.iterable(args[0]), *args[1:], **kwargs)))
        if name == "zip": return _check_value(list(zip(*(self.iterable(a) for a in args), **kwargs)))
        if name == "reversed": return _check_value(list(reversed(self.iterable(args[0]))))
        if name == "dict": return _check_value(dict(*args, **kwargs))
        if name in ("list", "tuple", "set"):
            target = {"list": list, "tuple": tuple, "set": set}[name]
            return _check_value(target(self.iterable(args[0])) if args else target())
        if name == "sum":
            start = args[1] if len(args) > 1 else kwargs.pop("start", 0)
            if kwargs or len(args) > 2 or type(start) is str:
                raise CandidateError("Invalid sum arguments")
            total = start
            for item in self.iterable(args[0]):
                # Do not delegate to native sum(list_of_lists, []): repeated
                # references could bypass per-container and deadline checks.
                total = self.binary(ast.Add(), total, item)
            return total
        functions = {"len": len, "str": str, "int": int, "float": float, "bool": bool,
                     "abs": abs, "round": round, "all": all, "any": any}
        if name not in functions: raise CandidateError("Unsupported builtin")
        if name in ("sum", "all", "any") and args: self.iterable(args[0])
        if name == "str" and args and not isinstance(args[0], (str, int, float, bool, type(None))):
            raise CandidateError("str conversion only supports scalars")
        return _check_value(functions[name](*args, **kwargs))

    def method(self, obj, name, args, kwargs):
        if name not in _METHODS.get(type(obj), set()): raise CandidateError("Forbidden method")
        if name in ("items", "keys", "values"):
            return _check_value(list(getattr(obj, name)(*args, **kwargs)))
        if name == "sort":
            key = kwargs.pop("key", None)
            if key is not None: kwargs["key"] = lambda value: self.call(key, [value], {})
        if name == "join":
            values = list(self.iterable(args[0]))
            if any(not isinstance(v, str) for v in values): raise CandidateError("join requires strings")
            if sum(map(len, values)) + len(obj) * max(0, len(values) - 1) > 65536:
                raise CandidateError("join output limit exceeded")
            args = [values]
        if name == "replace" and len(args) >= 2:
            count = obj.count(args[0]) if args[0] else len(obj) + 1
            if len(args) >= 3: count = min(count, max(0, args[2]))
            if len(obj) + count * max(0, len(args[1]) - len(args[0])) > 65536:
                raise CandidateError("replace output limit exceeded")
        if name == "extend" and args:
            values = list(self.iterable(args[0]))
            if len(obj) + len(values) > 4096: raise CandidateError("extend limit exceeded")
            args = [values]
        result = getattr(obj, name)(*args, **kwargs)
        _check_value(obj)
        return _check_value(result)


def _json_result(value):
    # Reject AST callable wrappers, cycles, non-string object keys and NaN.
    inspection_budget = 65536
    def inspect(item, depth=0):
        nonlocal inspection_budget
        inspection_budget -= 1
        if type(item) is str:
            inspection_budget -= len(item)
        if inspection_budget < 0:
            raise CandidateError("Output inspection size limit exceeded")
        if depth > 40: raise CandidateError("Output nesting limit exceeded")
        if type(item) in (str, int, float, bool, type(None)):
            _check_value(item)
        elif type(item) in (dict, list, tuple):
            _check_value(item)
            if isinstance(item, dict):
                if any(type(k) is not str for k in item): raise CandidateError("JSON object keys must be strings")
                inspection_budget -= sum(len(k) for k in item)
                for val in item.values(): inspect(val, depth + 1)
            else:
                for val in item: inspect(val, depth + 1)
        else:
            raise CandidateError("Output is not JSON-compatible")
    inspect(value)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded) > 65536: raise CandidateError("Output size limit exceeded")
    return json.loads(encoded)


def _execute_tree(tree, payload, deadline):
    try:
        interpreter = _Interpreter(tree, deadline=deadline)
        original = copy.deepcopy(payload)
        working = copy.deepcopy(payload)
        result = interpreter.call(interpreter.env.get("solve"), [working], {})
        if not _equal_json(original, working):
            raise CandidateError("Input mutation forbidden: solve(payload) changed payload")
        return _json_result(result)
    except CandidateError:
        raise
    except (Exception, RecursionError) as exc:
        raise CandidateError(f"Candidate runtime error: {type(exc).__name__}") from None


def _run_candidate_local(source: str, payload: dict):
    """Internal child-only entry; never call with model code in the host."""
    deadline = time.monotonic() + 2.0
    tree = _parse_source(source)
    return _execute_tree(tree, payload, deadline)


def run_candidate(source: str, payload: dict):
    """Hard-isolated AST evaluation: 5s wall cap, 256MiB and bounded IPC."""
    from .safe_executor import SafeExecutionError, SafeExecutorInfrastructureError, run_isolated
    try:
        return run_isolated({"operation": "run", "source": source, "payload": payload})
    except SafeExecutorInfrastructureError:
        raise
    except SafeExecutionError as exc:
        raise CandidateError(str(exc)) from None


CODE_FAMILIES = ("code_versions", "code_ledger", "code_config")


def _seeded(*parts):
    return int.from_bytes(hashlib.sha256("/".join(map(str, ("code-suite-v1",) + parts)).encode()).digest(), "big")


def _versions_reference(payload, rules):
    records = payload["records"]
    cutoff = payload["cutoff"]
    candidates = [r for r in records if r["kind"] != "retract" and r["time"] <= cutoff]
    revocations = [r for r in records if r["kind"] == "retract" and r["time"] <= cutoff]
    revoked = set()
    for row in candidates:
        for rev in revocations:
            if rev["target"] != row["id"]:
                continue
            if rules["retraction_scope"] == "not_after_retractor" and row["time"] > rev["time"]:
                continue
            if rules["qualified_retractions"]:
                strong_enough = (rev["authority"] >= row["authority"] if rules["authority"] == "higher"
                                 else rev["authority"] <= row["authority"])
                if not strong_enough:
                    continue
            revoked.add(row["id"])
    winners = {}
    for index, row in enumerate(records):
        if row["kind"] == "retract" or row["time"] > cutoff or row["id"] in revoked:
            continue
        key = row["key"].lower() if rules["keys"] == "lower" else row["key"]
        authority = row["authority"] if rules["authority"] == "higher" else -row["authority"]
        priority = ((authority, row["time"]) if rules["priority"] == "authority_then_time"
                    else (row["time"], authority))
        tie = (-index if rules["tie"] == "first" else index if rules["tie"] == "last" else row["id"])
        rank = priority + (tie,)
        if key not in winners or rank > winners[key][0]:
            winners[key] = (rank, row)
    return {"values": {k: row["value"] for k, (_, row) in winners.items() if row["kind"] == "set"},
            "sources": {k: row["id"] for k, (_, row) in winners.items()}}


def _ledger_reference(payload, rules):
    balances = dict(payload["initial"])
    frozen = set(payload["frozen"])
    events = payload["events"]
    cancelled = ({event["target"] for event in events if event["op"] == "cancel"}
                 if rules["cancel"] == "global" else set())
    seen, accepted = set(), []
    for event in events:
        if event["op"] == "cancel":
            if rules["cancel"] == "forward":
                cancelled.add(event["target"])
            continue
        if event["id"] in cancelled or event["id"] in seen:
            continue
        if rules["dedup"] == "first_seen":
            seen.add(event["id"])
        op, account = event["op"], event.get("account")
        applied = False
        if op == "credit":
            if rules["credit_frozen"] or account not in frozen:
                balances[account] += event["amount"]
                applied = True
        elif op == "debit":
            if account not in frozen and balances[account] >= event["amount"]:
                balances[account] -= event["amount"]
                applied = True
        elif op == "transfer":
            src, dst = event["from"], event["to"]
            unfrozen = src not in frozen and (not rules["transfer_requires_unfrozen_destination"] or dst not in frozen)
            if unfrozen and balances[src] >= event["amount"]:
                balances[src] -= event["amount"]
                balances[dst] += event["amount"]
                applied = True
        elif op == "freeze":
            applied = rules["count_noop_freeze"] or account not in frozen
            frozen.add(account)
        elif op == "thaw":
            applied = rules["count_noop_freeze"] or account in frozen
            frozen.discard(account)
        elif op == "bonus":
            amount = balances[event["if_account"]]
            condition = (amount >= event["threshold"] if rules["bonus_comparison"] == "ge"
                         else amount > event["threshold"])
            if condition and (rules["credit_frozen"] or account not in frozen):
                balances[account] += event["amount"]
                applied = True
        if applied:
            seen.add(event["id"])
            accepted.append(event["id"])
    return {"balances": balances, "frozen": sorted(frozen), "accepted": accepted}


def _config_reference(payload, rules):
    def key(name):
        return name.lower() if rules["keys"] == "lower" else name
    initial = {}
    for k, v in payload["defaults"].items():
        initial[key(k)] = v
    config = dict(initial)
    layers = list(enumerate(payload["layers"]))
    def rank(pair):
        index, layer = pair
        priority = layer["priority"] if rules["priority_order"] == "ascending" else -layer["priority"]
        tie = index if rules["tie"] == "input" else layer["id"]
        return priority, tie
    pending = [layer for _, layer in sorted(layers, key=rank)]
    applied, applied_ids = [], set()
    while pending:
        delayed, progressed = [], False
        for layer in pending:
            if not set(layer["requires"]).issubset(applied_ids):
                if rules["dependencies"] == "revisit":
                    delayed.append(layer)
                continue
            context = initial if rules["condition_context"] == "snapshot" else config
            condition = layer["when"]
            if condition is not None:
                k = key(condition["key"])
                if condition["op"] == "exists":
                    ok = k in context
                else:
                    ok = k in context and context[k] == condition["equals"]
                if not ok:
                    continue  # eligible-but-false conditions are final, not retried
            for k, value in layer["values"].items():
                k = key(k)
                if value is None and rules["null"] == "delete":
                    config.pop(k, None)
                elif rules["merge"] == "overwrite" or k not in config:
                    config[k] = value
            applied.append(layer["id"])
            applied_ids.add(layer["id"])
            progressed = True
        if rules["dependencies"] == "single_pass" or not progressed:
            break
        pending = delayed
    return {"config": config, "applied": applied,
            "blocked": [layer["id"] for layer in payload["layers"] if layer["id"] not in applied_ids]}


_SPECS = {
    "code_versions": (
        "Implement a document-version resolver. payload has cutoff and records with UNIQUE string ids. "
        "Each set/delete record has id,key,kind,time,authority and sets additionally have value. "
        "Each retract record has id,kind='retract',target,time,authority; targets are set/delete ids, "
        "never retract ids. Records are not time-sorted. First exclude every record with time > cutoff. "
        "A remaining retract can revoke its exact target: scope='global' ignores relative times; "
        "scope='not_after_retractor' permits revoking only targets with target.time <= retract.time. "
        "If qualified_retractions=true the retract must also have at least the target's authority "
        "under the configured authority direction; otherwise its authority does not matter. "
        "Revocations are collected before winner selection, independent of list position. "
        "Group remaining set/delete candidates by key, lowercasing keys only when keys='lower'. "
        "Prefer larger authority if authority='higher', smaller if 'lower'. Prefer larger time. "
        "priority selects which of those two criteria is primary; the other is secondary. "
        "Exact ties use first or last INPUT position, or lexicographically LARGEST full string id "
        "when tie='id_lex' (not numeric comparison). A winning delete omits its key from values "
        "but DOES appear in sources. Return {'values':{key:value},'sources':{key:winner_id}}. "
        "Only keys with eligible winners appear in sources. Return fresh objects; do not mutate input."
    ),
    "code_ledger": (
        "Implement an idempotent event ledger. payload contains initial balances (known account ids), "
        "initial frozen account ids, and events in execution order. All amounts and thresholds are "
        "nonnegative integers; all referenced accounts exist. cancel targets non-cancel event ids. "
        "When cancel='global', collect all cancel targets first and skip all occurrences of those ids, "
        "including earlier events. When cancel='forward', process cancel positions in order and block "
        "only later target occurrences; never undo earlier effects. cancel never enters accepted. "
        "For dedup='first_seen', mark each uncancelled unseen non-cancel id seen BEFORE testing its "
        "condition, even if rejected. For dedup='first_applied', mark only after execution: a rejected "
        "id can execute on a later occurrence with different payload. Always ignore already seen ids. "
        "credit adds amount, including to frozen accounts only if credit_frozen=true. debit executes "
        "only on an unfrozen account with enough funds. transfer requires enough source funds and "
        "unfrozen source; destination must also be unfrozen iff transfer_requires_unfrozen_destination. "
        "freeze/thaw set/clear frozen; a no-op counts as applied iff count_noop_freeze=true. "
        "bonus tests CURRENT balance of if_account against threshold using >= for ge or > for gt; "
        "if true it acts as credit to account with the same frozen rule. Rejected operations do "
        "nothing. A no-op freeze/thaw rejected for counting still leaves the same frozen state. "
        "Return {'balances':{account:int},'frozen':sorted_account_ids,'accepted':[executed event ids "
        "in execution order]}. Every applied event, including allowed no-ops, enters accepted once."
    ),
    "code_config": (
        "Implement conditional configuration resolution. payload has defaults and layers, each with "
        "UNIQUE id, priority, requires (layer ids), when (null or condition), values (a patch). "
        "Normalize all default/patch/condition keys to lower case iff keys='lower'; otherwise keep "
        "case. Within a mapping process keys in their insertion order, including normalization "
        "collisions. Copy defaults as initial config, preserving null defaults. Sort layers by "
        "priority ascending or descending per priority_order; ties use original input order for "
        "tie='input' or lexicographically ASCENDING full id for tie='id_lex'. Requires means ALL "
        "listed ids must have actually applied, including ids absent from input which never apply. "
        "For single_pass, visit the sorted list once and permanently skip unmet dependencies. "
        "For revisit, defer only unmet-dependency layers; after a full pass retry deferred layers "
        "in the same sorted relative order. Stop when a pass applies no layers. Conditions are "
        "tested only when dependencies are satisfied: exists requires key membership (even null), "
        "eq requires membership and equality to equals. condition_context='snapshot' uses the "
        "normalized defaults; 'live' uses the current config. A false condition permanently rejects "
        "that layer and is NEVER retried. For each applied patch, if null='delete' and value is "
        "null remove that key regardless of merge; else overwrite when merge='overwrite', or only "
        "insert absent keys when merge='preserve'. Applied includes eligible true-condition layers "
        "even if their patches change nothing. Return {'config':final_mapping,'applied':[layer ids "
        "in actual application order],'blocked':[all unapplied ids in ORIGINAL input order]}. "
        "Cycles, missing dependencies and condition-rejected prerequisites stay unapplied."
    ),
}

_STARTERS = {
    "code_versions": "def solve(payload):\n    values = {}\n    sources = {}\n    for row in payload['records']:\n        if row['kind'] == 'set':\n            values[row['key']] = row['value']\n            sources[row['key']] = row['id']\n    return {'values': values, 'sources': sources}\n",
    "code_ledger": "def solve(payload):\n    balances = dict(payload['initial'])\n    accepted = []\n    for event in payload['events']:\n        if event['op'] == 'credit':\n            balances[event['account']] += event['amount']\n            accepted.append(event['id'])\n        elif event['op'] == 'debit':\n            balances[event['account']] -= event['amount']\n            accepted.append(event['id'])\n    return {'balances': balances, 'frozen': [], 'accepted': accepted}\n",
    "code_config": "def solve(payload):\n    config = dict(payload['defaults'])\n    applied = []\n    for layer in payload['layers']:\n        config.update(layer['values'])\n        applied.append(layer['id'])\n    return {'config': config, 'applied': applied, 'blocked': []}\n",
}


def _rules(family, seed, split, index):
    n = (_seeded(seed, split, family, "semantics") + index)
    if family == "code_versions":
        return {"authority": ("higher", "lower")[n % 2],
                "priority": ("authority_then_time", "time_then_authority")[(n // 2) % 2],
                "keys": ("case_sensitive", "lower")[(n // 4) % 2],
                "tie": ("first", "last", "id_lex")[(n // 8) % 3],
                "qualified_retractions": bool((n // 24) % 2),
                "retraction_scope": ("global", "not_after_retractor")[(n // 48) % 2]}
    if family == "code_ledger":
        return {"cancel": ("global", "forward")[n % 2],
                "dedup": ("first_seen", "first_applied")[(n // 2) % 2],
                "credit_frozen": bool((n // 4) % 2),
                "transfer_requires_unfrozen_destination": bool((n // 8) % 2),
                "count_noop_freeze": bool((n // 16) % 2),
                "bonus_comparison": ("ge", "gt")[(n // 32) % 2]}
    return {"dependencies": ("single_pass", "revisit")[n % 2],
            "priority_order": ("ascending", "descending")[(n // 2) % 2],
            "tie": ("input", "id_lex")[(n // 4) % 2],
            "condition_context": ("snapshot", "live")[(n // 8) % 2],
            "null": ("delete", "literal")[(n // 16) % 2],
            "merge": ("overwrite", "preserve")[(n // 32) % 2],
            "keys": ("case_sensitive", "lower")[(n // 64) % 2]}


def _version_payload(rng, case):
    if case == 0:
        return {"cutoff": 5, "records": []}
    records = []
    for k in range(rng.randint(4, 18)):
        kind = "delete" if rng.random() < 0.22 else "set"
        row = {"id": f"D{rng.randint(1, 9)}x{k}", "kind": kind,
               "key": rng.choice(("Mode", "mode", "quota", "region")),
               "time": rng.randint(0, 8), "authority": rng.randint(1, 3)}
        if kind == "set": row["value"] = rng.choice(("red", "blue", "green", 0, 7, None))
        records.append(row)
    # 固定对抗结构不只换数：同 key 的日期/权威冲突、全字符串 ID 平局、删除及撤销。
    records.extend([
        {"id": "Z10", "kind": "set", "key": "Mode", "value": "tie-first", "time": 4, "authority": 2},
        {"id": "Z2", "kind": "set", "key": "Mode", "value": "tie-last", "time": 4, "authority": 2},
        {"id": "Delete", "kind": "delete", "key": "region", "time": 6, "authority": 3},
        {"id": "Future", "kind": "set", "key": "quota", "value": 999, "time": 10, "authority": 1},
    ])
    target_ids = [r["id"] for r in records]
    for k in range(rng.randint(1, 5)):
        records.append({"id": f"Revoke{k}", "kind": "retract", "target": rng.choice(target_ids),
                        "time": rng.randint(1, 9), "authority": rng.randint(1, 3)})
    if case % 3:
        rng.shuffle(records)
    return {"cutoff": rng.randint(4, 8), "records": records}


def _ledger_payload(rng, case):
    accounts = ("A", "B", "C")
    initial = {a: rng.randint(0, 90) for a in accounts}
    if case == 0:
        return {"initial": initial, "frozen": [], "events": []}
    events = []
    for k in range(rng.randint(8, 23)):
        op = rng.choice(("credit", "debit", "transfer", "freeze", "thaw", "bonus"))
        event = {"id": f"E{k}", "op": op}
        if op == "transfer":
            src, dst = rng.sample(accounts, 2)
            event.update({"from": src, "to": dst, "amount": rng.randint(0, 100)})
        else:
            event["account"] = rng.choice(accounts)
            if op in ("credit", "debit", "bonus"): event["amount"] = rng.randint(0, 100)
            if op == "bonus": event.update({"if_account": rng.choice(accounts), "threshold": rng.randint(0, 100)})
        events.append(event)
    # 相同ID的拒绝→重试是first_seen/first_applied的直接区别。
    events = [{"id": "retry", "op": "debit", "account": "A", "amount": 999},
              {"id": "retry", "op": "credit", "account": "A", "amount": 2},
              {"id": "noop", "op": "thaw", "account": "B"},
              {"id": "equal", "op": "bonus", "account": "C", "if_account": "B",
               "threshold": initial["B"], "amount": 3}] + events
    for k, original in enumerate(rng.sample(list(events), 2)):
        duplicate = dict(original)
        if "amount" in duplicate: duplicate["amount"] = rng.randint(0, 20)
        events.insert(rng.randint(0, len(events)), duplicate)
    for k, original in enumerate(rng.sample(list(events), 2)):
        events.insert(rng.randint(0, len(events)), {"id": f"cancel{k}", "op": "cancel", "target": original["id"]})
    frozen = [rng.choice(accounts)] if rng.random() < 0.5 else []
    return {"initial": initial, "frozen": frozen, "events": events}


def _config_payload(rng, case):
    defaults = {"Mode": "off", "mode": "on", "quota": rng.randint(0, 4), "obsolete": None}
    if case == 0:
        return {"defaults": defaults, "layers": []}
    n = rng.randint(5, 12)
    ids = [f"L{k}" for k in range(n)]
    layers = []
    for index, lid in enumerate(ids):
        requires = rng.sample(ids + ["MISSING"], rng.randint(0, 2))
        when = None
        if rng.random() < 0.55:
            when = {"key": rng.choice(("Mode", "mode", "quota", "new", "obsolete")),
                    "op": rng.choice(("exists", "eq"))}
            if when["op"] == "eq": when["equals"] = rng.choice(("on", "off", None, 1, 3))
        values = {}
        for _ in range(rng.randint(1, 3)):
            values[rng.choice(("Mode", "mode", "quota", "new", "obsolete"))] = rng.choice(("on", "off", None, 1, 3))
        layers.append({"id": lid, "priority": rng.randint(0, 3), "requires": requires,
                       "when": when, "values": values})
    # 明确包含前向依赖与条件后继，随后可能打乱以测试优先级/原输入平局。
    layers[0].update(requires=[ids[-1]], when=None, values={"new": "from-dependent"})
    layers[-1].update(requires=[], when=None, values={"Mode": "on", "quota": None})
    if n > 3:
        layers[1].update(requires=[], when={"key": "Mode", "op": "eq", "equals": "on"}, values={"quota": 7})
    if case % 2:
        rng.shuffle(layers)
    return {"defaults": defaults, "layers": layers}


def generate_code_suite(split: str = "dev", per_family: int = 3, seed: int = 20261103) -> list[dict]:
    """Generate 3*per_family tasks, each with 3 public and 30 hidden cases.

    Rules change across task indices, not just the data values. Hidden expected
    outputs are materialized with independent trusted reference implementations,
    not by executing the candidate or asking a model to judge itself.
    """
    if not isinstance(split, str) or not split:
        raise ValueError("split must be a nonempty string")
    if type(per_family) is not int or per_family < 1:
        raise ValueError("per_family must be a positive integer")
    generators = {"code_versions": _version_payload, "code_ledger": _ledger_payload, "code_config": _config_payload}
    references = {"code_versions": _versions_reference, "code_ledger": _ledger_reference, "code_config": _config_reference}
    tasks = []
    for family in CODE_FAMILIES:
        for index in range(per_family):
            rules = _rules(family, seed, split, index)
            examples, private_cases = [], []
            for visibility, count in (("public", 3), ("private", 30)):
                target = examples if visibility == "public" else private_cases
                for case in range(count):
                    rng = random.Random(_seeded(seed, split, family, index, visibility, case))
                    # Public examples are nonempty; hidden cases include empty-input boundaries.
                    payload = generators[family](rng, case + 1 if visibility == "public" else case)
                    target.append({"payload": payload, "expected": references[family](payload, rules)})
            public = {"function": "solve(payload)", "spec": _SPECS[family] + " IMPORTANT: solve must not mutate payload, including any nested object; return fresh result objects.", "rules": rules,
                      "starter_source": _STARTERS[family], "examples": examples,
                      "allowed_python_subset": ALLOWED_PYTHON_SUBSET}
            prompt = ("Repair the deliberately wrong starter and implement the complete specification, "
                      "not just the examples. The evaluator will call solve(payload) on unseen cases. "
                      "There are no external dependencies. The per-task semantic rules below are fixed "
                      "and are NOT repeated inside each runtime payload.\n\n"
                      + json.dumps(public, ensure_ascii=False, separators=(",", ":"))
                      + "\n\nReturn only a JSON object of the form {\"source\":\"complete Python source defining solve(payload)\"}.")
            tasks.append({"id": f"{split}_{family}_{index:03d}", "family": family, "split": split,
                          "prompt": prompt, "schema": {"source": "Python source defining solve(payload)"},
                          "public": public, "private": {"cases": private_cases},
                          "metadata": {"suite_seed": seed, "generator_version": "code-suite-v2-isolated-immutable",
                                       "public_case_count": 3, "private_case_count": 30,
                                       "semantic_signature": hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest()[:16],
                                       "executor": "isolated_bounded_ast_5s_256MiB_not_production_sandbox"}})
    return tasks


def _equal_json(left, right):
    # JSON bool and number must not be conflated by Python's True == 1.
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_equal_json(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_equal_json(a, b) for a, b in zip(left, right))
    return left == right


def _test_source_local(answer, cases, *, public):
    prefix = "public" if public else "hidden"
    total = len(cases)
    result = {"success": False, "score": 0.0, "violations": [], "valid_syntax": False,
              f"{prefix}_passed": 0, f"{prefix}_total": total}
    if not isinstance(answer, dict) or not isinstance(answer.get("source"), str):
        result["violations"] = ["answer must be an object containing source string"]
        return result
    deadline = time.monotonic() + 2.0
    try:
        tree = _parse_source(answer["source"])
    except CandidateError as exc:
        result["violations"] = [str(exc)]
        return result
    result["valid_syntax"] = True
    for index, case in enumerate(cases):
        if time.monotonic() > deadline:
            result["violations"].append("Validation timeout; remaining cases not executed")
            break
        try:
            actual = _execute_tree(tree, case["payload"], deadline)
            if _equal_json(actual, case["expected"]):
                result[f"{prefix}_passed"] += 1
            elif public:
                detail = json.dumps(actual, ensure_ascii=False, separators=(",", ":"))
                result["violations"].append(f"Public example {index + 1}: expected {json.dumps(case['expected'], ensure_ascii=False)}; got {detail[:1200]}")
            else:
                result["violations"].append(f"Hidden case {index + 1}: output mismatch")
        except CandidateError as exc:
            result["violations"].append(f"{prefix.capitalize()} case {index + 1}: {exc}")
            if "fuel" in str(exc).lower() or "timeout" in str(exc).lower():
                break
    passed = result[f"{prefix}_passed"]
    result["score"] = passed / total if total else 0.0
    result["success"] = total > 0 and passed == total
    # Keep tool feedback bounded without hiding whether all examples passed.
    result["violations"] = result["violations"][:8]
    return result


def validate_code_public(task: dict, answer: dict) -> dict:
    """Compile policy + public examples only; it never reads the private field."""
    return _test_source(answer, task["public"]["examples"], public=True)


def evaluate_code(task: dict, answer: dict) -> dict:
    """Final hidden deterministic assessment; no case details go to the solver."""
    return _test_source(answer, task["private"]["cases"], public=False)


def _test_source(answer, cases, *, public):
    """One child for the complete 3-public/30-hidden validation batch."""
    from .safe_executor import SafeExecutionError, SafeExecutorInfrastructureError, run_isolated
    try:
        return run_isolated({"operation": "test", "answer": answer, "cases": cases, "public": public})
    except SafeExecutionError as exc:
        prefix = "public" if public else "hidden"
        result = {"success": False, "score": 0.0, "violations": [str(exc)],
                "valid_syntax": False, f"{prefix}_passed": 0, f"{prefix}_total": len(cases),
                "isolated_worker_failed": True}
        if isinstance(exc, SafeExecutorInfrastructureError):
            result["executor_infrastructure_error"] = True
            if public:
                result["validator_error"] = True
        return result
