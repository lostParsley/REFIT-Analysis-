**Author:** Abhash Singh<br>
**Role:** Jr Data Scientist<br>
**Dataset:** REFIT Electrical Load Measurements
# REFIT Appliance Disaggregation Pipeline

My solution basically contains a modular, end-to-end Python pipeline which contains three parts: 
1. Cleaning raw REFIT smart meter data.  
2. Analyse washing-machine use across four households using the official cleaned data.
3. Train and finally estimate washing-machine load from aggregate household consumption. 

Also Building with Python-based data pipelines is my strong suit. So, instead of submitting a monolithic Jupyter notebook, I structured this solution as a production-ready Python package to ensure strict reproducibility, testability, and clear separation of concerns
## Repository Structure

*   `refit/`: Core package containing modules for data processing (`data.py`), exploratory analysis (`eda.py`), modelling (`model.py`), plotting (`plots.py`), and reporting (`report.py`).
*   `scripts/`: Executable scripts for pipeline automation, including `download_data.py`, `extract_data.py`, `check_submission.py`, and `package_submission.py`.
*   `tests/`: Unit tests validating core logic and data splitting (`test_core.py`, `test_validation.py`).
*   `config.json`: Centralized configuration for hyperparameters, file paths, and thresholds.
*   `DATA.md`: Detailed documentation on raw-data quality, cleaning steps, and gap/outlier handling.
*   `RESULTS.md`: EDA findings, model evaluation metrics, actual-vs-predicted plots, and failure case analysis.
*   `Recommendation.md`: Utility-facing business summary, practical energy-saving opportunities, and implications of lower-resolution smart-meter data.

## Setup and Execution

**1. Environment Setup**
Ensure you have Python 3.10+ installed. Create a virtual environment and install the required dependencies:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Data Ingestion**
Fetch and extract the University of Strathclyde REFIT datasets automatically using the provided scripts:
```bash
python -m scripts.download_data
python -m scripts.extract_data
```

**3. Run the Pipeline**
Execute the main pipeline, which processes the data, trains the model, and generates evaluation artifacts:
```bash
python -m refit
```

**4. Run Tests**
Verify the integrity of the data processing and validation splits:
```bash
pytest tests/
```
*Note: Pipeline outputs, including performance metrics and visualizations, are automatically saved to the `artifacts/tables/` and `output/` directories.*

## Preprocessing Decisions & Assumptions

*   **Resampling:** Raw data is strictly resampled to 1-minute intervals to standardize time steps.
*   **Duplicate Handling:** Duplicate timestamps are removed by keeping the first occurrence (or applying a median aggregation, detailed in `DATA.md`).
*   **Missing Data:** Short gaps (under a defined threshold) are forward-filled, while longer outages are explicitly flagged as `NaN` rather than interpolated, preventing the creation of artificial appliance cycles.
*   **Cycle Definition:** A washing-machine cycle is defined using a minimum power threshold and duration to filter out standby power noise, documented further in `RESULTS.md`. 

## Validation Design

To prevent data leakage, the model utilizes a strict out-of-sample validation strategy. 
*   **Approach:** Depending on the exact model configuration in `config.json`, the split is performed either chronologically (e.g., training on months 1-6, testing on months 7-8) or by isolation across households (training on Houses 1-3, testing on House 4).
*   **Rationale:** Random train/test splits on time-series data cause severe look-ahead bias due to the high autocorrelation of electrical loads. Chronological or spatial splitting ensures the model generalizes to unseen time periods or distinct household behavioral patterns.

## Trade offs

*   **Software Engineering vs. Notebooks:** Time was invested in building a robust, tested Python package (`refit/`) rather than an EDA-heavy notebook. This trades immediate visual interactivity for long-term maintainability and automated execution.
*   **Model Complexity:** The selected algorithm prioritizes interpretability, reliable baseline comparison, and execution speed over highly complex, black-box deep learning architectures that require GPU acceleration. 

## AI Tools Used

*   **Code Assistance:** AI tools (Gemini) were used to assist in structuring the project directory, generating unit test boilerplate, and refining documentation formatting to ensure alignment with assignment deliverables. All core data science logic, pipeline engineering, and analytical reasoning remain original.

## Possible Improvements

*   **Handling Simultaneous Appliances:** The current pipeline could struggle if high-load appliances (e.g., electric heaters, kettles) operate concurrently with the washing machine. Future iterations could incorporate multi-state models (like Factorial HMMs) to isolate overlapping signatures.
*   **Low-Resolution Adaptability:** The model is optimized for 1-minute intervals. Modifying the architecture to extract statistical features (mean, max, variance) over 15-minute rolling windows would improve adaptability for standard utility smart meters.

## Academic References

1. Murray, D., Stankovic, L., & Stankovic, V. (2017). **An electrical load measurements dataset of United Kingdom households from a two-year longitudinal study.** *Scientific Data, 4*, 160122. [https://doi.org/10.1038/sdata.2016.122](https://doi.org/10.1038/sdata.2016.122)
   Describes the REFIT dataset, how readings were collected, and the published cleaning process.

2. Friedman, J. H. (2001). **Greedy function approximation: A gradient boosting machine.** *The Annals of Statistics, 29*(5), 1189-1232. [https://doi.org/10.1214/aos/1013203451](https://doi.org/10.1214/aos/1013203451)
   
I was heavily inspired by this article and I took this as a background for the gradient-boosting approach used later in this project.

                            Thank You 

