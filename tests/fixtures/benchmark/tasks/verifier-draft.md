---
type: concept
title: "Product Quantization (PQ)"
sources:
  - "Jégou et al. (2011), Product Quantization for Nearest Neighbor Search — IEEE TPAMI"
---

## Summary

Product Quantization (PQ) compresses high-dimensional vectors by splitting each
vector into sub-vectors and quantizing each sub-space independently against a
small learned codebook, trading a bounded accuracy loss for a large reduction in
memory and distance-computation cost.

## Key Points

- Splits a D-dimensional vector into m sub-vectors, each quantized to one of k
  centroids, yielding an m·log2(k)-bit code.
- Enables asymmetric distance computation via precomputed lookup tables.

## Details

PQ is the basis of IVFADC and is widely combined with an inverted file index to
scale approximate nearest-neighbour search to billions of vectors.

## Sources

- Jégou, Douze, Schmid (2011), *Product Quantization for Nearest Neighbor Search*.
