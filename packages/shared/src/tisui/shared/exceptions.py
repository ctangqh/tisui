class TisuiCoreException(Exception):
    """Base exception for shared/core runtime failures."""


class ConfigError(TisuiCoreException):
    """Raised when runtime configuration is invalid."""


class MissingAPIKeyError(ConfigError):
    """Raised when a model provider API key is missing."""


class ModelError(TisuiCoreException):
    """Base exception for model invocation failures."""


class ModelTimeoutError(ModelError):
    """Raised when a model request times out."""


class ModelResponseError(ModelError):
    """Raised when a model returns an unusable response."""


class ModelUnsupportedError(ModelError):
    """Raised when an unknown model provider is requested."""


class ImageConstraintError(TisuiCoreException):
    """Base exception for image validation failures."""


class UnsupportedImageMimeTypeError(ImageConstraintError):
    """Raised when an image MIME type is unsupported."""


class ImageTooLargeError(ImageConstraintError):
    """Raised when an image exceeds allowed limits."""


class TooManyImagesError(ImageConstraintError):
    """Raised when too many images are supplied in one request."""


class ImagePreprocessFailedError(ImageConstraintError):
    """Raised when image preprocessing fails."""


__all__ = [
    "TisuiCoreException",
    "ConfigError",
    "MissingAPIKeyError",
    "ModelError",
    "ModelTimeoutError",
    "ModelResponseError",
    "ModelUnsupportedError",
    "ImageConstraintError",
    "UnsupportedImageMimeTypeError",
    "ImageTooLargeError",
    "TooManyImagesError",
    "ImagePreprocessFailedError",
]
