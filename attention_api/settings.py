"""
Django settings for attention_api project.

Generated by 'django-admin startproject' using Django 3.2.7.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/3.2/ref/settings/
"""
import os
import sys
from pathlib import Path

os.environ.setdefault('ATTENTION_API_KEY', 'django-insecure-e9q-4fjk_(--+=joxtbs$2d1km39!7!4_u15851pxjc0pu5e(k')

from . import production

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = production.BASE_DIR


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ['ATTENTION_API_KEY']

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['10.0.2.2']


# Application definition

INSTALLED_APPS = production.INSTALLED_APPS

AUTH_USER_MODEL = production.AUTH_USER_MODEL

MIDDLEWARE = production.MIDDLEWARE

ROOT_URLCONF = production.ROOT_URLCONF

TEMPLATES = production.TEMPLATES

WSGI_APPLICATION = production.WSGI_APPLICATION
ASGI_APPLICATION = production.ASGI_APPLICATION


# Database
# https://docs.djangoproject.com/en/3.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

LOGGING = production.LOGGING


# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = production.AUTH_PASSWORD_VALIDATORS


# Internationalization
# https://docs.djangoproject.com/en/3.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/

STATIC_URL = '/static/'

DATA_UPLOAD_MAX_MEMORY_SIZE = production.DATA_UPLOAD_MAX_MEMORY_SIZE

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = production.REST_FRAMEWORK

REST_KNOX = production.REST_KNOX

IS_TESTING = bool(set(sys.argv[:2]) & {"pytest", "test", "jenkins"}) and DEBUG

# We don't want to throttle while testing
if IS_TESTING:
    print('TESTING')
    # override your rest framework settings in test mode
    REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []
