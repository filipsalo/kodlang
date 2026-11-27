---
icon: lucide/database
---

# Key-value store

`stdlib/kv.kod` keeps a map from `str` keys to `bytes` values in a directory,
so that it survives the program, and a crash or a power cut: once `put` or
`remove` has returned, the change is on the disk.

```kod
import "kv"

func main() -> int64 or Error {
    let db = try kv.open("settings")
    try db.put("colour", kod_str_to_bytes("blue"))
    if db.get("colour") is bytes(value) {
        print(str(value))
    }
    try db.remove("colour")
    try db.close()
    return 0
}
```

| Call | Does |
|------|------|
| `kv.open(dir)` | opens the store in `dir`, making the directory if it isn't there (its parent must be); `kv.Store or Error` |
| `db.get(key)` | the value, or none; `bytes?` |
| `db.put(key, value)` | sets `key` to `value`, and returns once that is on the disk; `none or Error` |
| `db.remove(key)` | removes `key`, if it is there, and returns once that is on the disk; `none or Error` |
| `db.keys()` | the keys, sorted; `[str]` |
| `db.len()` | how many keys there are |
| `db.compact()` | writes what the store holds afresh, dropping the changes that led to it; `none or Error` |
| `db.close()` | closes its files; `none or Error` |
| `db.syncs` | how many times the store has synced its log, for measuring |

Everything the store holds is in memory as well: `get` doesn't read the disk.
It is for what fits in memory many times over, such as settings, sessions or
an index, not for a large data set.

## What is kept

- **What returned is kept.** `put` and `remove` write the change to the end of
  a log and sync it before they return. A crash after that, the machine's
  included, leaves it there.
- **What didn't return may be kept or not.** A change that was being
  written when the crash came is there after it, or isn't: never half of it.
- **A disk that fails stops the store.** When a write or a sync fails, the
  change may or may not reach the disk, and after a failed sync the system
  may have given up on what it was to write
  ([Disk faults](simulation.md#disk-faults)). So the store doesn't try
  again: that call, and every later one that changes it, fails with the
  error, while `get` and `keys` go on answering from memory. Opening the
  store again reads what is on the disk. A full disk (`StorageFull`) is
  the exception: the change is undone, nothing else is lost, and the store
  goes on, so that a program can make room and try again.

Tasks can share a store: changes go to the log in the order they were asked
for, and `get` sees each once its `put` has returned (not before: until then
it may not be on the disk).

## Many writers

A sync takes milliseconds (on a Mac's SSD, about 4), and the program waits for
it, every task included, so one sync for each change would hold a store to a
few hundred changes a second however many tasks make them. Instead, changes
that tasks make at the same time share a sync: a task whose change needs one
lets the others that are ready write theirs to the log first, then syncs once
for them all, and each of them returns once the sync has covered its own
change. One task alone syncs once for each change, as before.

512 puts to a store in `build/`, on a Mac's SSD:

| Tasks putting | One sync per change | Shared syncs |
|---------------|--------------------|--------------|
| 1 | 248 a second | 245 a second |
| 8 | 236 | 1,706 |
| 64 | 249 | 10,039 |

## On the disk

The directory holds two files:

- `log`: the changes since the last `compact`, one record each: its length
  and a CRC-32 of the rest (4 bytes each, little-endian), then a byte for
  the kind (1 put, 2 remove), the key's length (4 bytes), the key and the
  value.
- `snapshot`: what the store held at the last `compact`, as a record for
  each key, written the same way.

`open` reads the snapshot and then the log, each record changing what the
one before left. It stops at the first record that is cut short or whose
CRC is wrong, which only a crash in the middle of writing it leaves, at the
end; that tail is cut off, and new records go right after the last good one.

`compact` writes the snapshot to `snapshot.new`, syncs it, renames it over
`snapshot`, syncs the directory, and empties the log. A crash before the
rename leaves the old snapshot and the log; after it, the new one and a log
whose changes it already holds, or the end of such a log after a new record:
either way the old records change nothing when read again, since each key's
last record among them is what the snapshot holds.
`compact` runs by itself when the log has grown to four times the size of
what the store holds, and to at least a megabyte.

## Tested by crashing it

`stdlib/kv_test.kod` runs a store under a [simulation](simulation.md) with
crashes and disk faults: four tasks make changes the seed picks, noting each
that returned, while compaction runs now and then; after the crash, the
store has to hold every change that returned, and at most the one that
hadn't (each task's one in the middle). Over 500 seeds, none fails; with the
log's sync left out, 150 do; with the directory's sync after the snapshot's
rename left out, 109; and with a failed sync tried again instead of stopping
the store, 8. Of the
mistakes shared syncs invite, 26 seeds find a task that returns once any sync
has run, even one that began before its change was written, and 23 a
`compact` that empties the log before syncing what is in it.

## A service

`examples/kv_service/` serves a store over HTTP: `service.kod` has the
routes, `kv_service.kod` the program.

```
kod run examples/kv_service/kv_service.kod data 8080
curl -X PUT --data blue http://127.0.0.1:8080/keys/colour
curl http://127.0.0.1:8080/keys/colour
```

| Request | Answer |
|---------|--------|
| `GET /keys` | the keys, one a line |
| `GET /keys/{key}` | the value, or `404` |
| `PUT /keys/{key}` | sets it to the body: `200` once it is on the disk |
| `DELETE /keys/{key}` | removes it: `200` once that is on the disk |

A full disk is a `507`, and a store stopped by a failing disk a `503`; a
change answered either may or may not have been kept.

`service_test.kod` runs it under a simulation: the service and three clients
over the simulated network, a crash and disk faults as the seed picks, then a
restart that checks every change a client was answered `200` for. None of 200
seeds fails. A service that answered `200` whatever the store said fails under
60 of them, and one that answered before the change was synced (doing the
`put` in a task of its own) under 64.
