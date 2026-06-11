"""Unit tests for production model."""
import pytest
import torch
from src.main import BaseModel, Config

def test_model_initialization():
    config = Config('config.yaml')
    model = BaseModel(config)
    assert model is not None

def test_model_save_load(tmp_path):
    config = Config('config.yaml')
    model = BaseModel(config)
    
    save_path = tmp_path / 'test_model.pt'
    model.save(str(save_path))
    
    loaded = BaseModel.load(str(save_path))
    assert loaded is not None

def test_config_loading():
    config = Config('config.yaml')
    assert config.get('project.name') is not None
