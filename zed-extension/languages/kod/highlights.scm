; Highlight queries for Kod. Editor color schemes pick these up via
; the standard tree-sitter highlight capture names — @keyword,
; @string, @function, @type, etc. Kept conservative; we don't try to
; tag everything the parser exposes.

; ── Keywords ───────────────────────────────────────────────────────
[
  "import"
  "let"
  "extern"
  "func"
  "anon"
  "return"
  "if"
  "else"
  "for"
  "in"
  "struct"
  "type"
  "enum"
  "interface"
  "match"
  "is"
  "and"
  "or"
  "throw"
  "try"
  "must"
  "test"
  "assert"
] @keyword

; break / continue live inside their own statement nodes, so query them
; via the named-node form rather than the anonymous keyword token.
(break_statement) @keyword
(continue_statement) @keyword

; ── Operators ──────────────────────────────────────────────────────
[
  "="
  "+="
  "+"
  "-"
  "*"
  "/"
  "%"
  "=="
  "!="
  "<"
  "<="
  ">"
  ">="
  "->"
] @operator

; ── Literals ───────────────────────────────────────────────────────
(integer_literal) @number
(string_literal) @string
(fstring_literal) @string
(char_literal) @character
(boolean_literal) @constant.builtin
(none_literal) @constant.builtin

; ── Comments ───────────────────────────────────────────────────────
(line_comment) @comment

; ── Functions ──────────────────────────────────────────────────────
(function_declaration name: (identifier) @function)
(extern_declaration name: (identifier) @function)
(interface_method name: (identifier) @function)

(call_expression
  callee: (identifier) @function.call)

(call_expression
  callee: (field_expression name: (identifier) @function.method))

; ── Types ──────────────────────────────────────────────────────────
(type_alias name: (identifier) @type)
(struct_declaration name: (identifier) @type)
(enum_declaration name: (identifier) @type)
(interface_declaration name: (identifier) @type)

(named_type (identifier) @type)
(generic_type (identifier) @type)
(array_type (named_type (identifier) @type))

; ── Struct & enum bits ─────────────────────────────────────────────
(struct_field name: (identifier) @property)
(enum_variant name: (identifier) @constructor)
(enum_variant_field name: (identifier) @property)
(implicit_variant name: (identifier) @constructor)
(call_argument label: (identifier) @property)
(field_expression name: (identifier) @property)

; ── Tests ──────────────────────────────────────────────────────────
(test_declaration name: (string_literal) @function)

; ── Identifiers — fallback ─────────────────────────────────────────
(identifier) @variable
