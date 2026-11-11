# Raw Data Processing & Quality Report

This document outlines the exploratory inspection, quality assessment, and cleaning pipeline applied to the REFIT Electrical Load Measurements dataset, with a specific focus on House 1.

## 1. Raw-Data Coverage and Quality Findings

An initial audit of the raw House 1 dataset (`artifacts/tables/raw_house1_audit.json`) revealed several common sensor-data anomalies[cite: 1, 2]:

*   **Timestamp Parsing & Ordering:** The raw timestamps are provided as Unix epochs. While generally sequential, a small percentage of readings were found to be recorded out of chronological order, likely due to delayed packet transmission from the smart meter network.
*   **Duplicate Timestamps:** There were exact duplicate timestamps present in the raw data. Some were identical row duplications, while others had conflicting power readings for the exact same second.
*   **Irregular Intervals:** The REFIT dataset typically samples at roughly 8-second intervals, but the actual delta between rows varied significantly, with some readings clustered within 1-2 seconds and others experiencing minutes of downtime.
*   **Extreme Values & Impossibilities:** A few localized extreme spikes were detected in the aggregate channels (e.g., readings exceeding normal residential mains capacity, such as >20,000 Watts). Negative power readings, which are physically impossible in this context, were also flagged.

## 2. Cleaning Steps and Pipeline Decisions

To transform this raw data into a reliable format for modeling, a programmatic cleaning pipeline was constructed. The visual results of this transformation are available in `output/00_raw_cleaning.png`[cite: 1].

The pipeline performs the following ordered steps:

1.  **Timestamp Conversion & Sorting:** Unix epochs were parsed into localized `datetime` objects. The entire DataFrame was then sorted chronologically to fix the out-of-order anomalies.
2.  **Deduplication:** To handle duplicate timestamps, the pipeline drops exact row duplicates. Where duplicates had conflicting power values, the first recorded reading was kept (alternatively, a median could be applied) to ensure a strictly monotonic time index.
3.  **Resampling to 1-Minute Intervals:** The irregular 8-second data was resampled to a fixed 1-minute frequency. A mean aggregation was used for the downsampling to smooth out instantaneous sensor noise while preserving the total energy under the curve.
4.  **Handling Short Gaps vs. Long Outages:** 
    *   *Short gaps* (e.g., 1 to 3 minutes of missing data) were forward-filled. Given the thermal inertia of appliances and typical usage patterns, it is highly probable that the appliance state remained unchanged during a 2-minute sensor dropout.
    *   *Long outages* (> 3 minutes) were intentionally flagged and left as `NaN`. Forward-filling long gaps is dangerous in NILM (Non-Intrusive Load Monitoring) as it risks creating artificial, multi-hour "ghost" cycles that never actually occurred.
5.  **Outlier Clipping:** Negative values were clipped to `0`. Aggregate readings exceeding 20,000W (the rough limit of a UK domestic mains fuse) were capped, treating them as sensor miscalibrations.

## 3. Remaining Concerns and Limitations

While the cleaned data (`artifacts/tables/clean_house1_audit.json`) is ready for modeling, a few limitations remain[cite: 1, 4]:

*   **Unmetered Baselines:** The aggregate signal often contains base loads (routers, fridges, parasitic draw) that fluctuate. Resolving the washing machine signature against a noisy, shifting baseline remains a challenge.
*   **Missing Appliance Data:** Prolonged outages left as `NaN` mean we may lose the start or end of a washing machine cycle. The modeling approach must be robust enough to handle sequences with missing windows.
*   **Simultaneous Spikes:** Sudden power spikes in the aggregate load might belong to a kettle or microwave rather than the washing machine. Without higher-frequency transient data (e.g., 1Hz or higher), distinguishing these from the washing machine's heating element relies entirely on duration and cycle context.