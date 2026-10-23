# 実行ライブラリと配布物

- React / React DOM: MIT。Vite: MIT。TypeScript: Apache-2.0。
- Plotly.js strict distribution 2.32.0: MIT。配布bundleにライセンスを保持。
- lucide-react: ISC。fflate: MIT。
- Pyodide v314.0.7: Mozilla Public License 2.0。固定版CDNから実行環境とnumpy/pandas/scipy/scikit-learn等の対応パッケージを取得。各パッケージはそれぞれのライセンスで提供されます。
- XLSX読込用のopenpyxl 3.1.5 (MIT)、et_xmlfile 2.0.0 (MIT)はPyPIで配布されたpure Python wheelを`public/wheels/`に同梱。wheel内のLICENSEを保持し、同一サイトからmicropipで読み込みます。XLS用xlrd 2.0.2はPyodide配布を利用。
- 人工データは本アプリの検証用に生成。実測データ・個人情報は含みません。

原本: https://pypi.org/project/openpyxl/3.1.5/ 、https://pypi.org/project/et-xmlfile/2.0.0/ 、https://pyodide.org/en/stable/usage/packages-in-pyodide.html
