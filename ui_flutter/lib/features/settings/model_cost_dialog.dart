/// Settings → Models, 1.2.0: the screen a model above the suggestion shows first. It says plainly that the model is
/// above what is suggested for this PC and gives the figures the engine measured for it on the runtime this PC uses
/// (loading, answer or search time, peak memory, and the time to look at the photos again when its vectors differ).
/// Only measured figures: a figure measured on another PC says so, and nothing generic ever appears. A model that
/// is not recommended needs "Use anyway" here. Also the "Reset to suggested" question with its re-index time.
library;

import 'package:material_ui/material_ui.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/models_info.dart';
import '../../widgets/controls.dart';
import '../../widgets/dialogs.dart';
import '../consent/download_consent_dialog.dart' show ConsentFacts;
import 'pages/models.dart' show runtimeName;

/// The engine's sentence for [x] without its leading label ("Upgrade: Qwen3-VL 2B: more memory ..." becomes "more
/// memory ..."): the heading above the model already says which outcome it is.
String whyText(ModelInfo x) {
  final m = RegExp(r'^(Suggested|Upgrade|Lighter option|Not recommended|Not measured): [^:]+: ').firstMatch(x.why);
  return m == null ? x.why : x.why.substring(m.end);
}

/// "about 14 min", "about 2 h 15 min", "about 3 days": the time to look at the files again (the engine's hours).
String indexTime(double hours) {
  final m = (hours * 60).round();
  if (m < 1) return 'under a minute';
  if (m < 60) return 'about $m min';
  if (m < 48 * 60) {
    final h = m ~/ 60, mm = m % 60;
    return 'about $h h${mm == 0 ? '' : ' $mm min'}';
  }
  return 'about ${(m / 1440).round()} days';
}

String _mb(double v) => '${v.round().toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => ',')} MB';

String _n(double v) => v == v.roundToDouble() ? v.round().toString() : v.toStringAsFixed(2).replaceFirst(RegExp(r'0+$'), '');

/// Where the figures were measured, in words ("on this PC", "on a similar PC").
String costPlace(ModelInfo x) => x.cost.place;

/// The runtime the figures are for: a talk model's llama.cpp runtime (named as this PC has it), the processor for the
/// others ([info]: the catalogue, for the runtime's name).
String costRuntime(ModelInfo x, ModelsInfo info) {
  if (x.feature == 'talk') {
    final id = x.backend == 'vulkan' ? 'llama-vulkan' : 'llama-cpu';
    final rt = info.byId(id);
    return runtimeName(id, rt?.name ?? id, info.pc);
  }
  return x.backend == 'vulkan' ? 'the graphics adapter' : 'the processor';
}

/// The measured figures for [x] as (label, value) rows: only what was measured. Empty when nothing was.
List<(String, String)> costFacts(ModelInfo x, ModelsInfo info) {
  final k = x.cost;
  if (k.isEmpty) return const [];
  final talk = x.feature == 'talk';
  return [
    ('Measured', '${k.place}, on ${costRuntime(x, info)}'),
    if (k.loadS != null) ('Loading', 'about ${_n(k.loadS!)} s'),
    if (talk && k.answerS != null) ('Answer', 'the first word in about ${_n(k.answerS!.roundToDouble())} s'),
    if (!talk && k.queryMs != null) ('Search', 'a search takes about ${k.queryMs!.round()} ms'),
    if (!talk && k.itemsS != null) ('Indexing', '${_n(k.itemsS!)} photos a second'),
    if (k.ramMb != null)
      (
        'Peak memory',
        '${_mb(k.ramMb!)}${k.sharedMb != null && k.sharedMb! > 0 ? ' (${_mb(k.sharedMb!)} of it is the built-in graphics\' share of the PC\'s memory)' : ''}',
      ),
    if (k.gpuMb != null && k.gpuMb! > 0) ('Graphics card', '${_mb(k.gpuMb!)} of its own memory'),
    if (x.vectorsChange)
      (
        'Looking again',
        k.indexH == null
            ? 'Your files are looked at again for it, beside the current ones. How long this takes was not measured.'
            : 'Your photos are looked at again for it, beside the current ones: ${indexTime(k.indexH!)} '
                  '(${k.place}). The current ones keep answering until the new ones are done.',
      ),
  ];
}

/// One line with the cost, kept visible on a model chosen above the suggestion.
String costLine(ModelInfo x) {
  final k = x.cost;
  final parts = [
    if (k.loadS != null) 'loads in about ${_n(k.loadS!)} s',
    if (x.feature == 'talk' && k.answerS != null) 'first word in about ${_n(k.answerS!.roundToDouble())} s',
    if (x.feature != 'talk' && k.queryMs != null) 'a search takes about ${k.queryMs!.round()} ms',
    if (x.feature != 'talk' && k.itemsS != null) 'indexes ${_n(k.itemsS!)} photos a second',
    if (k.ramMb != null) 'peak memory ${_mb(k.ramMb!)}',
  ];
  return parts.isEmpty ? 'Nothing was measured for it on a PC like this one.' : '${parts.join(', ')} (measured ${k.place})';
}

/// The cost screen for [x] (above the suggestion): true = the user chose it ("Choose" / "Use anyway").
Future<bool> askModelCost(BuildContext context, ModelInfo x, ModelsInfo info) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (context) => ModelCostDialog(x: x, info: info),
  );
  return r ?? false;
}

class ModelCostDialog extends StatelessWidget {
  const ModelCostDialog({super.key, required this.x, required this.info});
  final ModelInfo x;
  final ModelsInfo info;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final facts = costFacts(x, info);
    final anyway = x.notRecommended;
    return NbDialog(
      title: anyway ? 'Use ${x.name} anyway?' : 'Choose ${x.name}?',
      width: 520,
      body: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            anyway
                ? "NOBAD Find doesn't recommend this one for this PC: ${whyText(x)}. You can still use it; the safety "
                      'limits still apply, so it waits, and says why, when memory is short.'
                : 'This is above what is suggested for this PC: ${whyText(x)}. You can use it; the safety limits '
                      'still apply, so it waits, and says why, when memory is short.',
          ),
          const SizedBox(height: NbSpace.x4),
          if (facts.isEmpty)
            Text(
              'Nothing was measured for this model on a PC like this one, so there are no figures to show.',
              style: NbType.text(13, c.text, height: 1.5),
            )
          else
            ConsentFacts(facts),
          if (x.cost.isEmpty || x.cost.here) const SizedBox.shrink() else ...[
            const SizedBox(height: NbSpace.x3),
            Text(
              'These figures were measured on ${x.cost.place.replaceFirst('on ', '')}, not on this PC.',
              style: NbType.text(12, c.dim, height: 1.4),
            ),
          ],
        ],
      ),
      actions: [
        // the safe answer has the focus: Enter never picks a heavier model by accident
        NbButton('Not now', kind: NbButtonKind.ghost, autofocus: true, onPressed: () => Navigator.pop(context, false)),
        NbButton(anyway ? 'Use anyway' : 'Choose ${x.name}', onPressed: () => Navigator.pop(context, true)),
      ],
    );
  }
}

/// "Reset to suggested": what would change, and the time to look at the files again; true = go ahead.
Future<bool> askReset(BuildContext context, List<ResetChange> changes) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (context) => ResetDialog(changes: changes),
  );
  return r ?? false;
}

class ResetDialog extends StatelessWidget {
  const ResetDialog({super.key, required this.changes});
  final List<ResetChange> changes;

  static String line(ResetChange c) {
    final again = c.feature == 'photo' ? 'your photos' : 'your files';
    return c.indexH == null
        ? "Looking at $again again isn't measured for ${c.name}, so no time is shown."
        : 'Looking at $again again takes ${indexTime(c.indexH!)} (measured on ${c.measuredOn == 'this PC' ? 'this PC' : 'a similar PC'}).';
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return NbDialog(
      title: 'Back to the suggested models?',
      width: 520,
      body: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'A different model means your files are looked at again, beside the current ones. The current ones keep '
            'answering until the new ones are done.',
          ),
          const SizedBox(height: NbSpace.x4),
          for (final ch in changes)
            Padding(
              padding: const EdgeInsets.only(bottom: NbSpace.x3),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${featureLabel(ch.feature)}: ${ch.fromName} to ${ch.name}',
                    style: NbType.text(13.5, c.text, weight: FontWeight.w600, height: 1.4),
                  ),
                  Text(line(ch), style: NbType.text(13, c.muted, height: 1.45)),
                  if (ch.needsDownload)
                    Text('It is not on this PC yet: you are asked before it downloads.',
                        style: NbType.text(13, c.muted, height: 1.45)),
                ],
              ),
            ),
        ],
      ),
      actions: [
        NbButton('Not now', kind: NbButtonKind.ghost, autofocus: true, onPressed: () => Navigator.pop(context, false)),
        NbButton('Reset', onPressed: () => Navigator.pop(context, true)),
      ],
    );
  }
}
