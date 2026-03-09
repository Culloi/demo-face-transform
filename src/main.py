#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
from PySide6.QtWidgets import QApplication
from ui_app import MainWindow

def main() -> None:
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
