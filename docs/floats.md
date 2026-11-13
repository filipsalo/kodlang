---
icon: lucide/percent
---

# Floating point

`float64` is a 64-bit IEEE 754 binary floating-point number, the type of
every JSON number that is not a whole number.

```kod
let price: float64 = 19.99
let total = price * 3.0 + 0.5
print(total.to_str())            // 60.47
```

## Literals

A float literal has digits on both sides of a point, an exponent, or both:

```kod
1.5
0.25
2e9
6.02e23
1.5e-3
1 000 000.5          // grouped like an integer
```

`1.` and `.5` are not literals: a point needs a digit after it, so that
`1.to_str()` still calls a method on the integer `1`. Nothing else turns an
integer into a float; `2` is an `int64` and `2.0` is a `float64`.

## Operators

| Operator | Operands | Result |
|----------|----------|--------|
| `+` `-` `*` `/` | two `float64` | `float64` |
| `-x` | a `float64` | `float64` |
| `<` `<=` `>` `>=` `==` `!=` | two `float64` | `bool` |

Nothing converts implicitly: `1.5 + 1` and `n * 0.5` with `n: int64` are
errors, and so is `%` on a float. Arithmetic follows IEEE 754 exactly, so
`1.0 / 0.0` is infinity, `0.0 / 0.0` is not a number, and a not-a-number
value is unequal to everything, itself included (`x != x` is how to
test for one, or `x.is_nan()`). There is no trap on overflow or division by
zero.

A `float64` is an ordinary value: it can be a variable, parameter, field,
array element (`[float64]`), optional (`float64?`) or a type argument
(`Box[float64]`). It cannot be a `Map` key or a `Set` member, because its
`==` is not an equivalence, and it has no literal pattern in a `match`.

## Conversions and methods

| Method | Result |
|---|---|
| `n.to_float64()` on an `int64` | the nearest `float64` |
| `x.to_int64()` | `x` truncated toward zero; a not-a-number is 0 and an out-of-range value saturates to the `int64` limits |
| `x.to_str()` | the shortest text that reads back as `x` (below) |
| `s.parse_float()` on a `str` | a `float64?`: none unless all of `s` is a decimal number, with an optional sign, a point and an exponent; `inf`, `nan` and hex are not accepted |
| `x.abs()` `x.floor()` `x.ceil()` `x.round()` `x.sqrt()` | the `float64` they name; `round` rounds halves away from zero |
| `x.is_nan()` `x.is_inf()` | `bool` |

`to_str` gives the fewest digits that parse back to exactly `x` (rounded half
to even from its exact value, when more than one such text has that many
digits), and always shows it is a float: `2.0`, not `2`. Magnitudes from `1e-6` up to `1e21` are
written without an exponent (`0.000001`, `123456789.5`); outside that range as
`1e+21` and `1.5e-7`. The special values are `inf`, `-inf` and `nan`. An
f-string uses `to_str`; `print` takes a `str`, so write `print(x.to_str())`.

`parse_float` gives the `float64` nearest the decimal value, however many
digits it has; a value exactly halfway between two floats goes to the one whose
last bit is 0. A value beyond the largest float is infinity, and one below half
the smallest is zero, with the sign kept. Both directions are Kod, in
`stdlib/primitives/float_text.kod`, with exact arithmetic on integers wider
than 64 bits where a float can't be trusted.

```kod
print((0.1 + 0.2).to_str())     // 0.30000000000000004
print((1.0).to_str())           // 1.0
print(("2.5e3".parse_float()?).to_str())   // 2500.0
```

## JSON

A JSON number that is not a whole `int64` keeps its text in a
[`Decimal`](json.md), so reading one as a float is `parse_float` on that text,
and writing one is `to_str`:

```kod
let text = item.get("price").as_number_text()?
let price = text.parse_float()?
let out = json.Value.Decimal(text: (price * 1.2).to_str())
```

`to_str` gives text that is a valid JSON number for every finite value. Infinity
and not-a-number have no JSON form: `emit` writes a `Decimal` whose text is not a
number as `null`, so `inf` and `nan` come out as `null`.

## Representation

A `float64` is the 8 bytes of its bit pattern, held in an ordinary register or
slot; the compiler moves it to a floating-point register only for the
operation. That is why it needs no new calling convention and an array of
them is an array of 8-byte words.
