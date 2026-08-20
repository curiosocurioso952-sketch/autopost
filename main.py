"""Ponto de entrada do AutoPost: python main.py"""
from autopost.main import AutoPost
from autopost import database as db

if __name__ == "__main__":
    db.close_connection()
    AutoPost().mainloop()
