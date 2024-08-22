/*
このプログラムはsakura.ioとTwilioとのコラボハンズオンにおいて、Twilio Functionsと連携させるためのものです。
outboundcallプログラムより本プログラムを実行することで、自動音声応答装置（IVR）として音声案内およびプッシュホンによる操作プログラム（turn）を実行させます。

本プログラムの動作に必要なパッケージはありません。

パラメータは以下のように指定します。
PATH : /ivr
ACCESS CONTROL ： チェックなし
EVENT ： 指定なし
*/
exports.handler = function(context, event, callback) {
  let twiml = new Twilio.twiml.VoiceResponse();
  // 音声の指定（声、言語） Audio specification
  let voiceParam = {};
  voiceParam.voice = 'alice';
  voiceParam.language = 'ja-JP';
  // ユーザによるキー入力の条件指定（桁数、タイムアウト値） Specify user's key input conditions
  let gatherParam = {};
  gatherParam.numDigits = 1;
  gatherParam.timeout = 10;
  // キー入力による分岐（turn）へのリダイレクトおよび初回の呼び出し内容（default）の指定 Specification of branch contents by key input
  switch (event.Digits) {
    case '0':
      twiml.say(voiceParam, 'エアコンを消します');
      twiml.redirect('https://'+context.DOMAIN_NAME+'/turn?switch=off');
      break;
    case '1':
      twiml.say(voiceParam, 'エアコンをつけます');
      twiml.redirect('https://'+context.DOMAIN_NAME+'/turn?switch=on');
      break;
    default:
      twiml.pause({"length": 2});
      twiml.gather(gatherParam)
        .say(voiceParam, '室温が上昇しています。エアコンをつける場合は１、消す場合は０を押してください');
  }
  callback(null, twiml);
};