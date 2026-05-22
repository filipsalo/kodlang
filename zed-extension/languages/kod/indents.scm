; Lines inside `{ ... }`, `[ ... ]`, `( ... )` indent one level.
; Zed inserts the indent automatically when Enter lands on a line
; whose start byte is captured @indent (open bracket) and whose end
; matches an @end (close).

[
  (block)
  (struct_body)
  (parameter_list)
  (array_literal)
  (parenthesized_expression)
] @indent

["{" "[" "("] @start
["}" "]" ")"] @end
