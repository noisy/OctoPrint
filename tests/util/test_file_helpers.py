# coding=utf-8
from __future__ import absolute_import

__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'
__copyright__ = "Copyright (C) 2015 The OctoPrint Project - Released under terms of the AGPLv3 License"

import unittest
import mock
import os

import octoprint.util

class BomAwareOpenTest(unittest.TestCase):
	"""
	Tests for :func:`octoprint.util.bom_aware_open`.
	"""

	def setUp(self):
		self.filename_utf8_with_bom = os.path.join(os.path.abspath(os.path.dirname(__file__)), "_files", "utf8_with_bom.txt")
		self.filename_utf8_without_bom = os.path.join(os.path.abspath(os.path.dirname(__file__)), "_files", "utf8_without_bom.txt")

	def test_bom_aware_open_with_bom(self):
		"""Tests that the contents of a UTF8 file with BOM are loaded correctly (without the BOM)."""

		# test
		with octoprint.util.bom_aware_open(self.filename_utf8_with_bom, encoding="utf-8") as f:
			contents = f.readlines()

		# assert
		self.assertEquals(len(contents), 3)
		self.assertTrue(contents[0].startswith("#"))

	def test_bom_aware_open_without_bom(self):
		"""Tests that the contents of a UTF8 file without BOM are loaded correctly."""

		# test
		with octoprint.util.bom_aware_open(self.filename_utf8_without_bom, encoding="utf-8") as f:
			contents = f.readlines()

		# assert
		self.assertEquals(len(contents), 3)
		self.assertTrue(contents[0].startswith("#"))

	def test_bom_aware_open_ascii(self):
		"""Tests that the contents of a UTF8 file loaded as ASCII are replaced correctly if "replace" is specified on errors."""

		# test
		with octoprint.util.bom_aware_open(self.filename_utf8_with_bom, errors="replace") as f:
			contents = f.readlines()

		# assert
		self.assertEquals(len(contents), 3)
		self.assertTrue(contents[0].startswith(u"\ufffd" * 3 + "#"))
		self.assertTrue(contents[2].endswith(u"\ufffd\ufffd" * 6))

	def test_bom_aware_open_encoding_error(self):
		"""Tests that an encoding error is thrown if not suppressed when opening a UTF8 file as ASCII."""
		try:
			with octoprint.util.bom_aware_open(self.filename_utf8_without_bom) as f:
				f.readlines()
			self.fail("Expected an exception")
		except UnicodeDecodeError:
			pass

	def test_bom_aware_open_parameters(self):
		"""Tests that the parameters are propagated properly."""

		with mock.patch("codecs.open") as mock_open:
			with octoprint.util.bom_aware_open(self.filename_utf8_without_bom, mode="rb", encoding="utf-8", errors="ignore") as f:
				f.readlines()

		mock_open.assert_called_once_with(self.filename_utf8_without_bom, encoding="utf-8", mode="rb", errors="ignore")

class TestAtomicWrite(unittest.TestCase):
	"""
	Tests for :func:`octoprint.util.atomic_write`.
	"""

	def setUp(self):
		pass

	@mock.patch("shutil.move")
	@mock.patch("tempfile.NamedTemporaryFile")
	def test_atomic_write(self, mock_tempfile, mock_move):
		"""Tests the regular basic "good" case."""

		# setup
		mock_file = mock.MagicMock()
		mock_file.name = "tempfile.tmp"
		mock_tempfile.return_value = mock_file

		# test
		with octoprint.util.atomic_write("somefile.yaml") as f:
			f.write("test")

		# assert
		mock_tempfile.assert_called_once_with(mode="w+b", prefix="tmp", suffix="", delete=False)
		mock_file.write.assert_called_once_with("test")
		mock_file.close.assert_called_once_with()
		mock_move.assert_called_once_with("tempfile.tmp", "somefile.yaml")

	@mock.patch("shutil.move")
	@mock.patch("tempfile.NamedTemporaryFile")
	def test_atomic_write_error_on_write(self, mock_tempfile, mock_move):
		"""Tests the error case where something in the wrapped code fails."""

		# setup
		mock_file = mock.MagicMock()
		mock_file.name = "tempfile.tmp"
		mock_file.write.side_effect = RuntimeError()
		mock_tempfile.return_value = mock_file

		# test
		try:
			with octoprint.util.atomic_write("somefile.yaml") as f:
				f.write("test")
			self.fail("Expected an exception")
		except RuntimeError:
			pass

		# assert
		mock_tempfile.assert_called_once_with(mode="w+b", prefix="tmp", suffix="", delete=False)
		mock_file.close.assert_called_once_with()
		self.assertFalse(mock_move.called)

	@mock.patch("shutil.move")
	@mock.patch("tempfile.NamedTemporaryFile")
	def test_atomic_write_error_on_move(self, mock_tempfile, mock_move):
		"""Tests the error case where the final move fails."""
		# setup
		mock_file = mock.MagicMock()
		mock_file.name = "tempfile.tmp"
		mock_tempfile.return_value = mock_file
		mock_move.side_effect = RuntimeError()

		# test
		try:
			with octoprint.util.atomic_write("somefile.yaml") as f:
				f.write("test")
			self.fail("Expected an exception")
		except RuntimeError:
			pass

		# assert
		mock_tempfile.assert_called_once_with(mode="w+b", prefix="tmp", suffix="", delete=False)
		mock_file.close.assert_called_once_with()
		self.assertTrue(mock_move.called)

	@mock.patch("shutil.move")
	@mock.patch("tempfile.NamedTemporaryFile")
	def test_atomic_write_parameters(self, mock_tempfile, mock_move):
		"""Tests that the open parameters are propagated properly."""

		# setup
		mock_file = mock.MagicMock()
		mock_file.name = "tempfile.tmp"
		mock_tempfile.return_value = mock_file

		# test
		with octoprint.util.atomic_write("somefile.yaml", mode="w", prefix="foo", suffix="bar") as f:
			f.write("test")

		# assert
		mock_tempfile.assert_called_once_with(mode="w", prefix="foo", suffix="bar", delete=False)
		mock_file.close.assert_called_once_with()
		mock_move.assert_called_once_with("tempfile.tmp", "somefile.yaml")
