# Kollektiv Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2024-12-29

Complete and full rebuild of the project.

### Added

- Content Service: Added a new service to handle content ingestion and processing end to end.
- Chat functionality: Exposed a chat API endpoint to chat with the content.
- Frontend integration: Integrated with a with React frontend application.

### Changed

- Updated documentations to reflect new project structure
- Updated to Python 3.12.6 -> 3.12.7
- Restructured project layout for better domain separation

### Fixed

- Fixed errors in streaming & non-streaming responses

### Security

- Added a new security policy
- Ratelimiting of API endpoints

## [0.1.6] - 2024-10-19

### Added

- Web UI: You can now chat with synced content via web interface. Built using Chainlit.

### Under development

- Basic evaluation suite is setup using Weave.

## [0.1.5] - 2024-10-19

### Changed

- Kollektiv is born - the project was renamed in order to exclude confusion with regards to Anthropic's Claude family of models.

## [0.1.4] - 2024-09-28

### Added

- Added Anthropic API exception handling

### Changed

- Updated pre-processing of chunker to remove images due to lack of multi-modal embeddings support

### Removed

- Removed redundant QueryGenerator class

### Fixed

- Fixed errors in streaming & non-streaming responses
