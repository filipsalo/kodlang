; Outline entries for Zed's symbol panel + breadcrumbs. Each capture
; is a name (@name) and a wrapping item (@item).

(function_declaration
  "func" @context
  name: (_) @name) @item

(struct_declaration
  "type" @context
  name: (_) @name) @item

(enum_declaration
  "type" @context
  name: (_) @name) @item

(interface_declaration
  "interface" @context
  name: (_) @name) @item

(type_alias
  "type" @context
  name: (_) @name) @item

(test_declaration
  "test" @context
  name: (_) @name) @item
