# Heronsgate Lab backup plan

Heronsgate Lab is a fictional organisation. This document is sample data for the retrieval suite
of the local-agent-stack evaluations; none of it describes a real place.

## Hosts

The primary storage server is named otter (192.0.2.41). Every night at 01:15 it replicates its
datasets to the backup server badger (192.0.2.42), which stands in a separate building.

## Retention

- Daily snapshots are kept for 30 days.
- Monthly snapshots are kept for 12 months.
- Yearly snapshots are kept for 7 years.

## Restore tests

A restore test of one randomly chosen dataset runs on the first Saturday of each quarter. The last
test restored the dataset media/photos in 47 minutes.
