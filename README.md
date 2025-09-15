# arrlist

Generate `artists.json` from a list of artist names.

Usage:

```
python generate_artists_json.py input.txt artists.json
```

Where `input.txt` contains one artist name per line. The script queries MusicBrainz for each name and writes an array of objects like:

```
[
  { "MusicBrainzId": "ca891d65-d9b0-4258-89f7-e6ba29d83767" }
]
```

Options:

- `--user-agent` User-Agent string for MusicBrainz. Default: `arrlist-generator/0.1.0 (https://github.com/jtreveset/arrlist)`
- `--delay` seconds between requests (default 1.1)
- `--retries` retry attempts for transient errors (default 3)
- `--strict` fail if any artist cannot be resolved

The script uses only Python’s standard library and respects MusicBrainz API rate limits.
