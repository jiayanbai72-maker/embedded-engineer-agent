"""Rebuild the offline page index after collecting or reviewing library files."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from embedded_agent.library import DocumentLibrary

if __name__=='__main__':
    print(DocumentLibrary(Path(__file__).resolve().parents[1]).build())
