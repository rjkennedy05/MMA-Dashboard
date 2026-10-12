import unittest

from normalizer import (
    coverage_without_history,
    find_profile_url,
    parse_profile_history,
    parse_profile_record,
    record_total,
    resolved_history_count,
)


SEARCH_HTML = """
<html><body><table>
  <tr><td><a href="/fighter/Jane-Doe-123">Jane Doe</a></td></tr>
</table></body></html>
"""

PROFILE_HTML = """
<html><body>
<div class="module fight_history">
  <div class="module_header"><h2>Fight History - Pro</h2></div>
  <table>
    <tr class="odd">
      <td><span class="final_result win">win</span></td>
      <td><a href="/fighter/Mary-Smith-456">Mary Smith</a></td>
      <td><a href="/events/Small-Show-99">Small Show 4</a><span class="sub_line">Jan / 02 / 2026</span></td>
      <td>Submission (Armbar)<span class="sub_line">Ref Name</span></td>
      <td>2</td><td>3:14</td>
    </tr>
  </table>
</div>
</body></html>
"""


class FighterHistoryNormalizerTests(unittest.TestCase):
    def test_finds_one_exact_profile(self):
        self.assertEqual(
            find_profile_url(SEARCH_HTML, "Jane Doe"),
            "https://www.sherdog.com/fighter/Jane-Doe-123",
        )

    def test_finds_unique_profile_despite_suffix_or_nickname(self):
        html = """
        <html><body>
          <a href="/fighter/Michael-Aswell-Jr-999">Michael Aswell Jr.</a>
        </body></html>
        """
        self.assertEqual(
            find_profile_url(html, "Michael Aswell"),
            "https://www.sherdog.com/fighter/Michael-Aswell-Jr-999",
        )

        nickname_html = """
        <html><body>
          <a href="/fighter/Jane-Doe-998">Jane &quot;Hammer&quot; Doe</a>
        </body></html>
        """
        self.assertEqual(
            find_profile_url(nickname_html, "Jane Doe"),
            "https://www.sherdog.com/fighter/Jane-Doe-998",
        )

    def test_does_not_count_cancelled_rows_as_completed_record_history(self):
        self.assertEqual(
            resolved_history_count([
                {"fight_status": "completed", "outcome": "W"},
                {"fight_status": "cancelled", "outcome": "CANCELLED"},
            ]),
            1,
        )

    def test_parses_profile_bout(self):
        history = parse_profile_history(
            PROFILE_HTML,
            "https://www.sherdog.com/fighter/Jane-Doe-123",
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["opponent_name"], "Mary Smith")
        self.assertEqual(history[0]["event_date"], "2026-01-02")
        self.assertEqual(history[0]["outcome"], "W")
        self.assertEqual(history[0]["finish_round"], 2)
        self.assertEqual(history[0]["finish_time_seconds"], 194)

    def test_parses_profile_record(self):
        self.assertEqual(
            parse_profile_record('<html><span class="record">8-2-1 (WIN-LOSS-DRAW)</span></html>'),
            "8-2-1",
        )

    def test_classifies_debut_and_unavailable_history(self):
        self.assertEqual(record_total("0-0-0"), 0)
        self.assertEqual(record_total("0-0-0 (1 NC)"), 1)
        self.assertEqual(coverage_without_history("0-0-0")[0], "confirmed_debut")
        self.assertEqual(coverage_without_history("6-2-0")[0], "regional_history_unavailable")
        self.assertEqual(coverage_without_history(None)[0], "history_unavailable")


if __name__ == "__main__":
    unittest.main()
