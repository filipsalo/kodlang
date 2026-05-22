/**
 * Tree-sitter grammar for Kod. The goal is editor-grade parsing —
 * good enough for syntax highlighting, code folding, and "go to next
 * function" without driving every corner of the language through the
 * grammar. Match expressions, f-string interpolations, refutable
 * `let .Pat(...) = ... else { }`, and generic instantiation are all
 * supported well enough to keep highlights from drifting on real code;
 * exotic cases fall back to ERROR nodes, which tree-sitter recovers
 * from gracefully.
 *
 * Sources of truth this aims to match: `stdlib/kod/lexing.kod` for
 * tokens and `stdlib/kod/parsing.kod` for shape — when in doubt, the
 * Kod parser is the spec.
 */

const PREC = {
  call: 14,
  index: 14,
  field: 13,
  unary: 12,
  mul: 11,
  add: 10,
  shift: 9,
  bitand: 8,
  bitxor: 7,
  bitor: 6,
  compare: 5,
  is: 4,
  and: 3,
  or: 2,
  range: 1,
  assign: 0,
};

module.exports = grammar({
  name: "kod",

  extras: ($) => [/\s/, $.line_comment],

  word: ($) => $.identifier,

  conflicts: () => [],

  rules: {
    source_file: ($) => repeat($._top_level),

    _top_level: ($) =>
      choice(
        $.import_declaration,
        $.extern_declaration,
        $.function_declaration,
        $.type_alias,
        $.struct_declaration,
        $.enum_declaration,
        $.interface_declaration,
        $.test_declaration,
      ),

    line_comment: () => token(seq("//", /[^\n]*/)),

    // ── Top-level declarations ────────────────────────────────────────

    import_declaration: ($) =>
      seq(
        "import",
        field("path", $.string_literal),
        optional(
          seq(
            "{",
            sepBy(",", field("item", $.identifier)),
            optional(","),
            "}",
          ),
        ),
      ),

    extern_declaration: ($) =>
      seq(
        "extern",
        "func",
        field("name", $.identifier),
        field("params", $.parameter_list),
        optional(seq("->", field("return_type", $._type))),
      ),

    function_declaration: ($) =>
      seq(
        "func",
        field("name", $.identifier),
        field("params", $.parameter_list),
        optional(seq("->", field("return_type", $._type))),
        field("body", $.block),
      ),

    type_alias: ($) =>
      seq("type", field("name", $.identifier), "=", field("target", $._type)),

    struct_declaration: ($) =>
      seq(
        "type",
        field("name", $.identifier),
        optional($.type_parameters),
        "=",
        "struct",
        field("body", $.struct_body),
      ),

    type_parameters: ($) =>
      seq("[", sepBy1(",", $.identifier), optional(","), "]"),

    struct_body: ($) =>
      seq(
        "{",
        repeat(choice($.struct_field, $.function_declaration)),
        "}",
      ),

    struct_field: ($) =>
      seq(field("name", $.identifier), ":", field("type", $._type)),

    enum_declaration: ($) =>
      seq(
        "type",
        field("name", $.identifier),
        "=",
        "enum",
        "{",
        repeat($.enum_variant),
        "}",
      ),

    enum_variant: ($) =>
      seq(
        field("name", $.identifier),
        optional(
          seq(
            "(",
            sepBy(",", $.enum_variant_field),
            optional(","),
            ")",
          ),
        ),
      ),

    enum_variant_field: ($) =>
      seq(field("name", $.identifier), ":", field("type", $._type)),

    interface_declaration: ($) =>
      seq(
        "interface",
        field("name", $.identifier),
        "{",
        repeat($.interface_method),
        "}",
      ),

    interface_method: ($) =>
      seq(
        "func",
        field("name", $.identifier),
        field("params", $.parameter_list),
        optional(seq("->", field("return_type", $._type))),
      ),

    test_declaration: ($) =>
      seq(
        "test",
        field("name", $.string_literal),
        field("body", $.block),
      ),

    // ── Parameters ────────────────────────────────────────────────────

    parameter_list: ($) =>
      seq("(", sepBy(",", $.parameter), optional(","), ")"),

    parameter: ($) =>
      seq(
        optional("anon"),
        // Swift-style `label name: type` — both halves optional in
        // different ways. `self` takes no type annotation.
        field("first", $.identifier),
        optional(field("second", $.identifier)),
        optional(seq(":", field("type", $._type))),
      ),

    // ── Types ─────────────────────────────────────────────────────────

    _type: ($) =>
      choice(
        $.optional_type,
        $.throws_type,
        $._type_suffix,
      ),

    _type_suffix: ($) => choice($.array_type, $.generic_type, $.named_type),

    named_type: ($) =>
      seq(
        $.identifier,
        repeat(seq(".", $.identifier)),
      ),

    array_type: ($) => seq("[", $._type, "]"),

    generic_type: ($) =>
      seq(
        $.identifier,
        "[",
        sepBy1(",", $._type),
        optional(","),
        "]",
      ),

    optional_type: ($) => seq($._type_suffix, "?"),

    throws_type: ($) => seq($._type_suffix, "or", $.identifier),

    // ── Statements ────────────────────────────────────────────────────

    block: ($) => seq("{", repeat($._statement), "}"),

    _statement: ($) =>
      choice(
        $.let_declaration,
        $.let_else_declaration,
        $.assignment,
        $.return_statement,
        $.if_statement,
        $.for_statement,
        $.foreach_statement,
        $.break_statement,
        $.continue_statement,
        // No match_statement — match-as-statement and match-as-expression
        // are syntactically identical, so we keep just `match_expression`
        // and reach it via expression_statement.
        $.throw_statement,
        $.assert_statement,
        $.expression_statement,
      ),

    let_declaration: ($) =>
      seq(
        "let",
        field("name", $.identifier),
        optional(seq(":", field("type", $._type))),
        "=",
        field("value", $._expression),
      ),

    // `let .Pat(bindings) = expr else { ... }` — refutable destructure.
    // Pinned to a `.`-prefixed lhs so it doesn't compete with the plain
    // `let name = expr` form; the body of the variant (whether a call
    // shape or bare `.Variant`) is just an expression for highlighting.
    let_else_declaration: ($) =>
      seq(
        "let",
        field("pattern", $._dotted_pattern),
        "=",
        field("value", $._expression),
        "else",
        field("else_body", $.block),
      ),

    _dotted_pattern: ($) =>
      choice(
        $.implicit_variant,
        seq(
          $.implicit_variant,
          "(",
          sepBy(",", $.identifier),
          optional(","),
          ")",
        ),
      ),

    assignment: ($) =>
      prec.right(
        PREC.assign,
        seq(
          field("lhs", $._expression),
          choice("=", "+="),
          field("rhs", $._expression),
        ),
      ),

    return_statement: ($) =>
      prec.right(seq("return", optional($._expression))),

    if_statement: ($) =>
      prec.right(
        seq(
          "if",
          field("condition", $._expression),
          field("then", $.block),
          optional(seq("else", field("else", choice($.block, $.if_statement)))),
        ),
      ),

    for_statement: ($) =>
      seq("for", field("condition", $._expression), field("body", $.block)),

    foreach_statement: ($) =>
      seq(
        "for",
        field("binding", $.identifier),
        "in",
        field("iter", $._expression),
        field("body", $.block),
      ),

    break_statement: () => "break",
    continue_statement: () => "continue",

    match_arm: ($) =>
      choice(
        // `else` arm: arrow optional (matches the Kod parser).
        seq("else", optional("->"), field("body", choice($.block, $._statement))),
        // Pattern arm: arrow required so the grammar knows where the
        // pattern ends. Patterns are syntactically expressions —
        // `.Variant(bindings)` shows up as a call on an implicit
        // variant; highlighting doesn't need to distinguish.
        seq(
          field("pattern", $._expression),
          "->",
          field("body", choice($.block, $._statement)),
        ),
      ),

    throw_statement: ($) => seq("throw", $._expression),

    assert_statement: ($) => seq("assert", $._expression),

    expression_statement: ($) => $._expression,

    // ── Expressions ───────────────────────────────────────────────────

    _expression: ($) =>
      choice(
        $.match_expression,
        $.try_expression,
        $.must_expression,
        $.binary_expression,
        $.unary_expression,
        $.call_expression,
        $.field_expression,
        $.index_expression,
        $.slice_expression,
        $.parenthesized_expression,
        $.array_literal,
        $.implicit_variant,
        $.integer_literal,
        $.string_literal,
        $.fstring_literal,
        $.char_literal,
        $.boolean_literal,
        $.none_literal,
        $.identifier,
      ),

    parenthesized_expression: ($) => seq("(", $._expression, ")"),

    binary_expression: ($) => {
      const table = [
        ["or", PREC.or],
        ["and", PREC.and],
        ["==", PREC.compare],
        ["!=", PREC.compare],
        ["<", PREC.compare],
        ["<=", PREC.compare],
        [">", PREC.compare],
        [">=", PREC.compare],
        ["is", PREC.is],
        ["+", PREC.add],
        ["-", PREC.add],
        ["*", PREC.mul],
        ["/", PREC.mul],
        ["%", PREC.mul],
      ];
      return choice(
        ...table.map(([op, p]) =>
          prec.left(
            p,
            seq(
              field("lhs", $._expression),
              field("op", op),
              field("rhs", $._expression),
            ),
          ),
        ),
      );
    },

    unary_expression: ($) =>
      prec.right(PREC.unary, seq(field("op", "-"), $._expression)),

    call_expression: ($) =>
      prec(
        PREC.call,
        seq(
          field("callee", $._expression),
          "(",
          sepBy(",", $.call_argument),
          optional(","),
          ")",
        ),
      ),

    call_argument: ($) =>
      choice(
        seq(field("label", $.identifier), ":", field("value", $._expression)),
        field("value", $._expression),
      ),

    field_expression: ($) =>
      prec.left(
        PREC.field,
        seq(field("object", $._expression), ".", field("name", $.identifier)),
      ),

    index_expression: ($) =>
      prec(
        PREC.index,
        seq(
          field("object", $._expression),
          "[",
          field("index", $._expression),
          "]",
        ),
      ),

    slice_expression: ($) =>
      prec(
        PREC.index,
        seq(
          field("object", $._expression),
          "[",
          optional(field("lo", $._expression)),
          ":",
          optional(field("hi", $._expression)),
          "]",
        ),
      ),

    array_literal: ($) =>
      seq("[", sepBy(",", $._expression), optional(","), "]"),

    implicit_variant: ($) =>
      seq(".", field("name", $.identifier)),

    match_expression: ($) =>
      seq(
        "match",
        field("subject", $._expression),
        "{",
        repeat($.match_arm),
        "}",
      ),

    try_expression: ($) => prec(PREC.unary, seq("try", $._expression)),
    must_expression: ($) => prec(PREC.unary, seq("must", $._expression)),

    // ── Literals ──────────────────────────────────────────────────────

    integer_literal: () => /-?[0-9]+/,

    boolean_literal: () => choice("true", "false"),
    none_literal: () => "none",

    // Triple-quoted strings (`"""..."""` / `f"""..."""`) need an
    // external scanner because tree-sitter regex has no look-ahead;
    // dropped for now — they're rare in real code and tree-sitter
    // recovers from the ERROR node gracefully.
    string_literal: ($) =>
      seq(
        '"',
        repeat(choice($._string_escape, /[^"\\\n]/)),
        '"',
      ),

    _string_escape: () => /\\./,

    fstring_literal: ($) =>
      seq(
        'f"',
        repeat(
          choice(
            $.fstring_interpolation,
            $._string_escape,
            /[^{"\\\n]/,
          ),
        ),
        '"',
      ),

    fstring_interpolation: ($) => seq("{", $._expression, "}"),

    char_literal: () =>
      token(
        seq(
          "'",
          choice(/[^'\\\n]/, seq("\\", /./)),
          "'",
        ),
      ),

    identifier: () => /[a-zA-Z_][a-zA-Z0-9_]*/,
  },
});

// Comma- (or other-) separated list helpers.
function sepBy(sep, rule) {
  return optional(sepBy1(sep, rule));
}

function sepBy1(sep, rule) {
  return seq(rule, repeat(seq(sep, rule)));
}
